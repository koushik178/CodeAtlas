"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Repository = {
  id: number;
  name: string;
  github_url: string;
  description: string | null;
  default_branch: string | null;
  owner: string | null;
  stars: number;
  forks: number;
  primary_language: string | null;
  created_at: string;
};

type ImportedRepository = {
  id: number;
  owner: string | null;
  name: string;
  full_name: string;
  github_url: string;
  description: string | null;
  language: string | null;
  default_branch: string | null;
  stars: number;
  forks: number;
  created_at: string;
};

type SourceReference = {
  chunk_id: number;
  path: string;
  start_line: number;
  end_line: number;
};

type RepositoryAnswer = {
  repository_id: number;
  question: string;
  model: string;
  answer: string;
  sources: SourceReference[];
};

type CodeReviewFinding = {
  severity: "critical" | "high" | "medium" | "low";
  category: "bugs" | "maintainability" | "security" | "code_quality" | "performance";
  description: string;
  file_path: string;
  start_line: number;
  end_line: number;
  chunk_id: number;
  suggested_improvement: string;
};

type CodeReview = {
  repository_id: number;
  model: string;
  findings: CodeReviewFinding[];
  scanned_chunks: number;
  scanned_files: number;
  scope_note: string;
};

type RepositoryFile = {
  id: number;
  path: string;
  filename: string;
  extension: string | null;
  language: string | null;
  size: number | null;
  github_sha: string;
  has_content: boolean;
};

type RepositoryFileTree = {
  repository_id: number;
  files: RepositoryFile[];
};

type TestGeneration = {
  repository_id: number;
  source_file_path: string;
  language: string;
  framework: string;
  test_file_path: string;
  explanation: string;
  test_code: string;
  source_chunks: number;
  review_notice: string;
};

type ApiError = { detail?: string };

const apiUrl = process.env.NEXT_PUBLIC_API_URL;

function formatCount(value: number) {
  return new Intl.NumberFormat("en-US", { notation: "compact" }).format(value);
}

function apiErrorMessage(body: ApiError | null, fallback: string) {
  return body?.detail || fallback;
}

export default function Home() {
  const [backendStatus, setBackendStatus] = useState("Checking...");
  const [githubUrl, setGithubUrl] = useState("");
  const [repository, setRepository] = useState<Repository | null>(null);
  const [importedRepositories, setImportedRepositories] = useState<ImportedRepository[]>([]);
  const [repositoryFilter, setRepositoryFilter] = useState("");
  const [isLoadingRepositories, setIsLoadingRepositories] = useState(true);
  const [repositoryListError, setRepositoryListError] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importNotice, setImportNotice] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<RepositoryAnswer[]>([]);
  const [askError, setAskError] = useState<string | null>(null);
  const [isAsking, setIsAsking] = useState(false);
  const [review, setReview] = useState<CodeReview | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [isReviewing, setIsReviewing] = useState(false);
  const [repositoryFiles, setRepositoryFiles] = useState<RepositoryFile[]>([]);
  const [selectedSourcePath, setSelectedSourcePath] = useState("");
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [fileListError, setFileListError] = useState<string | null>(null);
  const [testFocus, setTestFocus] = useState("");
  const [testGeneration, setTestGeneration] = useState<TestGeneration | null>(null);
  const [testGenerationError, setTestGenerationError] = useState<string | null>(null);
  const [isGeneratingTests, setIsGeneratingTests] = useState(false);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);

  useEffect(() => {
    async function checkBackend() {
      if (!apiUrl) {
        setBackendStatus("Not configured");
        return;
      }
      try {
        const response = await fetch(`${apiUrl}/health`);
        if (!response.ok) throw new Error("Backend request failed");
        const data: { status: string } = await response.json();
        setBackendStatus(data.status);
      } catch (requestError) {
        console.error(requestError);
        setBackendStatus("Disconnected");
      }
    }
    void checkBackend();
    void loadImportedRepositories();
  }, []);

  useEffect(() => {
    async function loadRepositoryFiles() {
      if (!repository) {
        return;
      }
      if (!apiUrl) {
        setFileListError("NEXT_PUBLIC_API_URL is not configured.");
        return;
      }
      setIsLoadingFiles(true);
      setFileListError(null);
      try {
        const response = await fetch(`${apiUrl}/api/repositories/${repository.id}/files`);
        const body = (await response.json().catch(() => null)) as RepositoryFileTree | ApiError | null;
        if (!response.ok || !body || !("files" in body)) {
          throw new Error(apiErrorMessage(body as ApiError | null, "Unable to load repository files."));
        }
        const availableFiles = body.files.filter((file) => file.has_content);
        setRepositoryFiles(availableFiles);
        setSelectedSourcePath(availableFiles[0]?.path || "");
      } catch (requestError) {
        setRepositoryFiles([]);
        setSelectedSourcePath("");
        setFileListError(requestError instanceof Error ? requestError.message : "Unable to load repository files.");
      } finally {
        setIsLoadingFiles(false);
      }
    }
    void loadRepositoryFiles();
  }, [repository]);

  async function loadImportedRepositories(): Promise<ImportedRepository[] | null> {
    if (!apiUrl) {
      setIsLoadingRepositories(false);
      setRepositoryListError("NEXT_PUBLIC_API_URL is not configured.");
      return null;
    }

    setIsLoadingRepositories(true);
    setRepositoryListError(null);
    try {
      const response = await fetch(`${apiUrl}/api/repositories`);
      const body = (await response.json().catch(() => null)) as ImportedRepository[] | ApiError | null;
      if (!response.ok || !Array.isArray(body)) {
        throw new Error(apiErrorMessage(body as ApiError | null, "Unable to load imported repositories."));
      }
      setImportedRepositories(body);
      return body;
    } catch (requestError) {
      setRepositoryListError(requestError instanceof Error ? requestError.message : "Unable to load imported repositories.");
      return null;
    } finally {
      setIsLoadingRepositories(false);
    }
  }

  function selectRepository(nextRepository: Repository) {
    setRepository(nextRepository);
    setAnswers([]);
    setQuestion("");
    setAskError(null);
    setReview(null);
    setReviewError(null);
    setRepositoryFiles([]);
    setSelectedSourcePath("");
    setTestFocus("");
    setTestGeneration(null);
    setTestGenerationError(null);
    setCopyNotice(null);
  }

  async function importRepository(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setImportError(null);
    setImportNotice(null);

    if (!githubUrl.trim()) {
      setImportError("Paste a public GitHub repository URL to continue.");
      return;
    }
    if (!apiUrl) {
      setImportError("NEXT_PUBLIC_API_URL is not configured.");
      return;
    }

    setIsImporting(true);
    try {
      const response = await fetch(`${apiUrl}/api/repositories/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ github_url: githubUrl.trim() }),
      });
      const body = (await response.json().catch(() => null)) as Repository | ApiError | null;
      if (response.status === 409) {
        const repositories = await loadImportedRepositories();
        const existing = repositories?.find((item) => sameGitHubRepository(item.github_url, githubUrl));
        if (existing) {
          selectRepository(repositoryFromList(existing));
          setImportNotice("This repository was already imported, so the existing repository is now open.");
          return;
        }
      }
      if (!response.ok) {
        throw new Error(apiErrorMessage(body as ApiError | null, "Unable to import this repository. Please try again."));
      }
      selectRepository(body as Repository);
      await loadImportedRepositories();
      setImportNotice("Repository imported and selected.");
    } catch (requestError) {
      setImportError(requestError instanceof Error ? requestError.message : "Unable to import this repository. Please try again.");
    } finally {
      setIsImporting(false);
    }
  }

  async function askRepository(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAskError(null);

    if (!repository) {
      setAskError("Import a repository before asking a question.");
      return;
    }
    if (!question.trim()) {
      setAskError("Enter a question about the selected repository.");
      return;
    }
    if (!apiUrl) {
      setAskError("NEXT_PUBLIC_API_URL is not configured.");
      return;
    }

    setIsAsking(true);
    try {
      const response = await fetch(`${apiUrl}/api/repositories/${repository.id}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim(), limit: 5 }),
      });
      const body = (await response.json().catch(() => null)) as RepositoryAnswer | ApiError | null;
      if (!response.ok) {
        throw new Error(apiErrorMessage(body as ApiError | null, "Unable to answer this repository question. Please try again."));
      }
      setAnswers((currentAnswers) => [...currentAnswers, body as RepositoryAnswer]);
      setQuestion("");
    } catch (requestError) {
      setAskError(requestError instanceof Error ? requestError.message : "Unable to answer this repository question. Please try again.");
    } finally {
      setIsAsking(false);
    }
  }

  async function reviewRepository() {
    setReviewError(null);
    if (!repository) {
      setReviewError("Import a repository before starting a code review.");
      return;
    }
    if (!apiUrl) {
      setReviewError("NEXT_PUBLIC_API_URL is not configured.");
      return;
    }

    setIsReviewing(true);
    try {
      const response = await fetch(`${apiUrl}/api/repositories/${repository.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_findings: 10 }),
      });
      const body = (await response.json().catch(() => null)) as CodeReview | ApiError | null;
      if (!response.ok) {
        throw new Error(apiErrorMessage(body as ApiError | null, "Unable to review this repository. Please try again."));
      }
      setReview(body as CodeReview);
    } catch (requestError) {
      setReviewError(requestError instanceof Error ? requestError.message : "Unable to review this repository. Please try again.");
    } finally {
      setIsReviewing(false);
    }
  }

  async function generateTests(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTestGenerationError(null);
    setCopyNotice(null);
    if (!repository || !selectedSourcePath) {
      setTestGenerationError("Select a source file before generating tests.");
      return;
    }
    if (!apiUrl) {
      setTestGenerationError("NEXT_PUBLIC_API_URL is not configured.");
      return;
    }
    setIsGeneratingTests(true);
    try {
      const response = await fetch(`${apiUrl}/api/repositories/${repository.id}/tests/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: selectedSourcePath, focus: testFocus.trim() || null }),
      });
      const body = (await response.json().catch(() => null)) as TestGeneration | ApiError | null;
      if (!response.ok) {
        throw new Error(apiErrorMessage(body as ApiError | null, "Unable to generate unit tests. Please try again."));
      }
      setTestGeneration(body as TestGeneration);
    } catch (requestError) {
      setTestGenerationError(requestError instanceof Error ? requestError.message : "Unable to generate unit tests. Please try again.");
    } finally {
      setIsGeneratingTests(false);
    }
  }

  async function copyGeneratedTests() {
    if (!testGeneration) return;
    try {
      await navigator.clipboard.writeText(testGeneration.test_code);
      setCopyNotice("Test code copied to your clipboard.");
    } catch {
      setCopyNotice("Copy failed. Select the code manually and copy it.");
    }
  }

  const statusIsHealthy = backendStatus === "healthy";
  const filteredRepositories = useMemo(() => {
    const query = repositoryFilter.trim().toLocaleLowerCase();
    if (!query) return importedRepositories;
    return importedRepositories.filter((item) => [
      item.name,
      item.owner,
      item.full_name,
      item.language,
      item.description,
    ].some((value) => value?.toLocaleLowerCase().includes(query)));
  }, [importedRepositories, repositoryFilter]);

  return (
    <main className="ca-shell min-h-screen px-4 py-6 text-zinc-100 sm:px-6 sm:py-10 lg:px-8">
      <div className="ca-grid pointer-events-none fixed inset-0 -z-10" aria-hidden="true" />
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 sm:gap-8">
        <header className="flex flex-col gap-5 border-b border-zinc-800/80 pb-7 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="ca-section-label mb-3">Repository intelligence</p>
            <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">CodeAtlas</h1>
            <p className="mt-3 max-w-2xl text-base leading-7 text-zinc-400">A focused workspace for repository context, grounded answers, code review, and test suggestions.</p>
          </div>
          <div className="inline-flex items-center gap-2 self-start rounded-full border border-zinc-800 bg-zinc-900/80 px-3 py-1.5 text-sm text-zinc-300 shadow-sm shadow-black/20">
            <span className={`h-2 w-2 rounded-full ${statusIsHealthy ? "bg-emerald-400" : "bg-amber-400"}`} aria-hidden="true" />
            Backend: <span className="font-medium text-zinc-100">{backendStatus}</span>
          </div>
        </header>

        <nav aria-label="Workspace sections" className="sticky top-3 z-20 flex flex-col gap-3 rounded-2xl border border-zinc-800/90 bg-zinc-950/85 px-4 py-3 shadow-lg shadow-black/20 backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <span className="ca-section-label">Workspace</span>
          <div className="flex flex-wrap gap-1.5">
            <a className="ca-nav-link" href="#repositories">Repositories</a>
            {repository && <>
              <a className="ca-nav-link" href="#overview">Overview</a>
              <a className="ca-nav-link" href="#qa">Q&amp;A</a>
              <a className="ca-nav-link" href="#review">Review</a>
              <a className="ca-nav-link" href="#tests">Unit tests</a>
              <a className="ca-nav-link" href="#health">Health</a>
            </>}
          </div>
        </nav>

        <section id="repositories" className="ca-surface scroll-mt-24 rounded-2xl p-5 sm:p-7" aria-labelledby="repository-import-heading">
          <div className="mb-6">
            <p className="ca-section-label">Repository import</p>
            <h2 id="repository-import-heading" className="mt-2 text-xl font-semibold text-white">Import or open a repository</h2>
            <p className="mt-2 text-sm leading-6 text-zinc-400">Paste a public URL, such as <span className="font-mono text-zinc-300">https://github.com/owner/repository</span>.</p>
          </div>
          <form onSubmit={importRepository} className="flex flex-col gap-3 sm:flex-row">
            <label className="sr-only" htmlFor="github-url">GitHub repository URL</label>
            <input id="github-url" type="url" value={githubUrl} onChange={(event) => setGithubUrl(event.target.value)} placeholder="https://github.com/owner/repository" disabled={isImporting} className="min-w-0 flex-1 rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-sm text-white outline-none transition placeholder:text-zinc-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60" />
            <button type="submit" disabled={isImporting} className="inline-flex min-h-12 items-center justify-center rounded-xl bg-cyan-400 px-5 py-3 text-sm font-bold text-zinc-950 transition hover:bg-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-zinc-900 disabled:cursor-not-allowed disabled:bg-cyan-400/60">
              {isImporting ? "Importing..." : "Analyze Repository"}
            </button>
          </form>
          <div className="mt-4 min-h-6" aria-live="polite">
            {isImporting && <p className="ca-alert-info">Fetching repository metadata from GitHub...</p>}
            {importError && <p role="alert" className="ca-alert-error">{importError}</p>}
            {importNotice && <p className="rounded-lg border border-emerald-900/70 bg-emerald-950/30 px-3 py-2 text-sm text-emerald-300">{importNotice}</p>}
          </div>
        </section>

        <section className="ca-surface scroll-mt-24 rounded-2xl p-5 sm:p-7" aria-labelledby="imported-repositories-heading">
          <div className="border-b border-zinc-800 pb-5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
              <p className="ca-section-label">Repository library</p>
              <h2 id="imported-repositories-heading" className="mt-2 text-xl font-semibold text-white">Imported repositories</h2>
              <p className="mt-1 text-sm text-zinc-400">Open an existing repository to continue its Q&A and code-review work.</p>
              </div>
              {!isLoadingRepositories && <span className="self-start rounded-full border border-zinc-700 bg-zinc-950 px-3 py-1 font-mono text-xs text-zinc-300 sm:self-auto">{importedRepositories.length} {importedRepositories.length === 1 ? "repository" : "repositories"}</span>}
            </div>
            <div className="relative mt-4">
              <label className="sr-only" htmlFor="repository-filter">Search imported repositories</label>
              <input id="repository-filter" type="search" value={repositoryFilter} onChange={(event) => setRepositoryFilter(event.target.value)} placeholder="Search by repository, owner, language, or description" disabled={isLoadingRepositories || importedRepositories.length === 0} className="w-full rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-2.5 text-sm text-white outline-none transition placeholder:text-zinc-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-50" />
            </div>
          </div>
          <div className="mt-5" aria-live="polite">
            {isLoadingRepositories && <p className="ca-alert-info">Loading imported repositories...</p>}
            {repositoryListError && <p role="alert" className="ca-alert-error">{repositoryListError}</p>}
            {!isLoadingRepositories && !repositoryListError && importedRepositories.length === 0 && <p className="ca-empty">No repositories have been imported yet. Import a public GitHub repository above to begin.</p>}
            {!isLoadingRepositories && !repositoryListError && importedRepositories.length > 0 && (
              filteredRepositories.length > 0 ? (
                <div className="repository-scrollbar max-h-[31rem] overflow-y-auto pr-1 sm:max-h-[32rem]">
                  <ul className="grid gap-2">
                    {filteredRepositories.map((item) => <ImportedRepositoryCard key={item.id} item={item} isSelected={repository?.id === item.id} onSelect={() => selectRepository(repositoryFromList(item))} />)}
                  </ul>
                </div>
              ) : <p className="ca-empty">No repositories match your search.</p>
            )}
          </div>
        </section>

        {repository && (
          <>
            <section id="overview" className="scroll-mt-24 rounded-2xl border border-emerald-900/60 bg-emerald-950/20 p-5 shadow-xl shadow-black/10 sm:p-7" aria-live="polite" aria-labelledby="repository-overview-heading">
              <div className="flex flex-col gap-3 border-b border-emerald-900/50 pb-5 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="ca-section-label text-emerald-400">Selected repository</p>
                  <h2 id="repository-overview-heading" className="mt-2 text-2xl font-semibold text-white">{repository.name}</h2>
                  {repository.owner && <p className="mt-1 text-sm text-zinc-400">Owned by {repository.owner}</p>}
                </div>
                <a href={repository.github_url} target="_blank" rel="noreferrer" className="text-sm font-medium text-cyan-300 underline decoration-cyan-500/50 underline-offset-4 hover:text-cyan-200">Open on GitHub ↗</a>
              </div>
              <p className="mt-5 leading-7 text-zinc-300">{repository.description || "No repository description was provided."}</p>
              <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Metadata label="Default branch" value={repository.default_branch || "Not specified"} />
                <Metadata label="Language" value={repository.primary_language || "Not specified"} />
                <Metadata label="Stars" value={formatCount(repository.stars)} />
                <Metadata label="Forks" value={formatCount(repository.forks)} />
              </dl>
            </section>

            <section id="qa" className="ca-surface scroll-mt-24 rounded-2xl p-5 sm:p-7" aria-labelledby="repository-qa-heading">
              <div className="flex flex-col gap-2 border-b border-zinc-800 pb-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="ca-section-label">Repository Q&amp;A</p>
                  <h2 id="repository-qa-heading" className="mt-2 text-xl font-semibold text-white">Ask about this repository</h2>
                  <p className="mt-1 text-sm text-zinc-400">Answers are grounded in the repository&apos;s indexed source chunks.</p>
                </div>
                <span className="rounded-full border border-cyan-900/70 bg-cyan-950/30 px-3 py-1 font-mono text-xs text-cyan-200">repo #{repository.id}</span>
              </div>

              <div className="mt-6 space-y-5" aria-live="polite">
                {answers.length === 0 && !isAsking && <p className="ca-empty">Try asking where configuration is loaded, how a route works, or which files handle a feature.</p>}
                {answers.map((item, index) => <QuestionAnswerCard key={`${item.repository_id}-${index}-${item.question}`} item={item} />)}
                {isAsking && <div className="ca-alert-info">Searching repository context and composing an answer...</div>}
              </div>

              <form onSubmit={askRepository} className="mt-6">
                <label className="text-sm font-medium text-zinc-200" htmlFor="repository-question">Question</label>
                <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-end">
                  <textarea id="repository-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Where is the database connection configured?" rows={3} disabled={isAsking} className="min-h-24 min-w-0 flex-1 resize-y rounded-xl border border-zinc-700 bg-zinc-950 px-4 py-3 text-sm leading-6 text-white outline-none transition placeholder:text-zinc-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60" />
                  <button type="submit" disabled={isAsking || !question.trim()} className="inline-flex min-h-12 shrink-0 items-center justify-center rounded-xl bg-cyan-400 px-5 py-3 text-sm font-bold text-zinc-950 transition hover:bg-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-zinc-900 disabled:cursor-not-allowed disabled:bg-cyan-400/60">
                    {isAsking ? "Asking..." : "Ask CodeAtlas"}
                  </button>
                </div>
              </form>
              {askError && <p role="alert" className="ca-alert-error mt-4">{askError}</p>}
            </section>

            <section id="review" className="ca-surface scroll-mt-24 rounded-2xl p-5 sm:p-7" aria-labelledby="code-review-heading">
              <div className="flex flex-col gap-4 border-b border-zinc-800 pb-5 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="ca-section-label">Automated analysis</p>
                  <h2 id="code-review-heading" className="mt-2 text-xl font-semibold text-white">Automated code review</h2>
                  <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-400">Review a bounded set of relevant source chunks for evidence-based concerns. It is not a static-analysis or correctness guarantee.</p>
                </div>
                <button type="button" onClick={reviewRepository} disabled={isReviewing} className="inline-flex min-h-12 shrink-0 items-center justify-center rounded-xl border border-violet-400/50 bg-violet-400/10 px-5 py-3 text-sm font-bold text-violet-100 transition hover:bg-violet-400/20 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:ring-offset-2 focus:ring-offset-zinc-900 disabled:cursor-not-allowed disabled:opacity-60">
                  {isReviewing ? "Reviewing..." : review ? "Run review again" : "Run code review"}
                </button>
              </div>

              <div className="mt-5" aria-live="polite">
                {isReviewing && <p className="ca-alert-info border-violet-900/70 bg-violet-950/20 text-violet-200">Retrieving a bounded source sample and reviewing it...</p>}
                {review && !isReviewing && <CodeReviewResults review={review} />}
                {reviewError && <p role="alert" className="ca-alert-error">{reviewError}</p>}
              </div>
            </section>

            <section id="tests" className="ca-surface scroll-mt-24 rounded-2xl p-5 sm:p-7" aria-labelledby="unit-test-heading">
              <div className="border-b border-zinc-800 pb-5">
                <p className="ca-section-label">Generated coverage</p>
                <h2 id="unit-test-heading" className="mt-2 text-xl font-semibold text-white">Unit-test generation</h2>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-zinc-400">Generate a focused test suggestion from one stored source file. CodeAtlas never writes generated code into your repository.</p>
              </div>

              {isLoadingFiles && <p className="ca-alert-info mt-5">Loading source files...</p>}
              {fileListError && <p role="alert" className="ca-alert-error mt-5">{fileListError}</p>}
              {!isLoadingFiles && !fileListError && repositoryFiles.length === 0 && <p className="ca-empty mt-5">No stored source files are available for test generation in this repository.</p>}

              {!isLoadingFiles && !fileListError && repositoryFiles.length > 0 && (
                <form onSubmit={generateTests} className="mt-5">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                      <label className="text-sm font-medium text-zinc-200" htmlFor="test-source-file">Source file</label>
                      <select id="test-source-file" value={selectedSourcePath} onChange={(event) => setSelectedSourcePath(event.target.value)} disabled={isGeneratingTests} className="mt-2 w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3 py-3 font-mono text-sm text-white outline-none transition focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60">
                        {repositoryFiles.map((file) => <option key={file.id} value={file.path}>{file.path}{file.language ? ` · ${file.language}` : ""}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="text-sm font-medium text-zinc-200" htmlFor="test-focus">Function or module focus <span className="font-normal text-zinc-500">(optional)</span></label>
                      <input id="test-focus" type="text" value={testFocus} onChange={(event) => setTestFocus(event.target.value)} maxLength={300} placeholder="e.g. parse_github_repository_url" disabled={isGeneratingTests} className="mt-2 w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3 py-3 text-sm text-white outline-none transition placeholder:text-zinc-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-60" />
                    </div>
                  </div>
                  <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <p className="text-xs leading-5 text-amber-200">Generated tests are suggestions only. Review and adapt them before adding them to your repository.</p>
                    <button type="submit" disabled={isGeneratingTests || !selectedSourcePath} className="inline-flex min-h-11 shrink-0 items-center justify-center rounded-xl border border-cyan-400/50 bg-cyan-400/10 px-4 py-2 text-sm font-bold text-cyan-100 transition hover:bg-cyan-400/20 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-zinc-900 disabled:cursor-not-allowed disabled:opacity-60">
                      {isGeneratingTests ? "Generating tests..." : "Generate tests"}
                    </button>
                  </div>
                </form>
              )}

              {testGenerationError && <p role="alert" className="ca-alert-error mt-5">{testGenerationError}</p>}
              {testGeneration && (
                <div className="mt-6 overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/70">
                  <div className="flex flex-col gap-3 border-b border-zinc-800 bg-zinc-900/80 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="font-mono text-sm font-semibold text-cyan-200">{testGeneration.test_file_path}</p>
                      <p className="mt-1 text-xs text-zinc-400">{testGeneration.language} · {testGeneration.framework} · {testGeneration.source_chunks} source chunks</p>
                    </div>
                    <button type="button" onClick={copyGeneratedTests} className="inline-flex min-h-9 items-center justify-center rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm font-semibold text-zinc-200 transition hover:border-zinc-500 hover:text-white focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-zinc-900">Copy test code</button>
                  </div>
                  <div className="px-4 py-4">
                    <p className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">Generation notes</p>
                    <p className="mt-2 text-sm leading-6 text-zinc-300">{testGeneration.explanation}</p>
                    <p className="mt-4 rounded-lg border border-amber-900/60 bg-amber-950/20 px-3 py-2 text-xs leading-5 text-amber-200">{testGeneration.review_notice}</p>
                    {copyNotice && <p className="mt-3 text-sm text-cyan-200" aria-live="polite">{copyNotice}</p>}
                  </div>
                  <pre className="repository-scrollbar max-h-[32rem] overflow-auto border-t border-zinc-800 bg-black/30 p-4 text-xs leading-6 text-zinc-200"><code>{testGeneration.test_code}</code></pre>
                </div>
              )}
            </section>

            <section id="health" className="ca-surface scroll-mt-24 rounded-2xl p-5 sm:p-7" aria-labelledby="health-score-heading">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <p className="ca-section-label">Repository insights</p>
                  <h2 id="health-score-heading" className="mt-2 text-xl font-semibold text-white">Health score</h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-400">A dedicated repository health assessment belongs here once that capability is introduced.</p>
                </div>
                <span className="self-start rounded-full border border-zinc-700 bg-zinc-950 px-3 py-1 font-mono text-xs text-zinc-400">Planned</span>
              </div>
              <div className="mt-5 rounded-xl border border-dashed border-zinc-700 bg-zinc-950/40 p-4 text-sm leading-6 text-zinc-400">
                Health scoring is not calculated yet. Existing repository analysis remains available above; this area is intentionally a clear placeholder rather than a simulated score.
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function CodeReviewResults({ review }: { review: CodeReview }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-zinc-400">
        <span>{review.scanned_files} files · {review.scanned_chunks} source chunks reviewed</span>
        <span className="font-mono text-xs text-zinc-500">{review.model}</span>
      </div>
      <p className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/20 px-3 py-2 text-xs leading-5 text-amber-200">{review.scope_note}</p>
      {review.findings.length === 0 ? (
        <p className="mt-4 rounded-xl border border-emerald-900/60 bg-emerald-950/20 px-4 py-4 text-sm leading-6 text-emerald-200">No evidence-based findings were returned for the reviewed source sample. This does not prove the repository is free of issues.</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {review.findings.map((finding, index) => <CodeReviewFindingCard key={`${finding.chunk_id}-${index}-${finding.description}`} finding={finding} />)}
        </ul>
      )}
    </div>
  );
}

function CodeReviewFindingCard({ finding }: { finding: CodeReviewFinding }) {
  return (
    <li className="rounded-xl border border-zinc-800 bg-zinc-950/70 p-4 shadow-sm shadow-black/10">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-wrap gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-xs font-bold uppercase ${severityClassName(finding.severity)}`}>{finding.severity}</span>
          <span className="rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-300">{finding.category.replace("_", " ")}</span>
        </div>
        <span className="font-mono text-xs text-cyan-200">{finding.file_path}:{finding.start_line}–{finding.end_line}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-zinc-200">{finding.description}</p>
      <div className="mt-4 border-l-2 border-violet-400/70 pl-3">
        <p className="text-xs font-semibold tracking-wide text-violet-200 uppercase">Suggested improvement</p>
        <p className="mt-1 text-sm leading-6 text-zinc-300">{finding.suggested_improvement}</p>
      </div>
      <p className="mt-3 font-mono text-xs text-zinc-500">chunk {finding.chunk_id}</p>
    </li>
  );
}

function severityClassName(severity: CodeReviewFinding["severity"]) {
  const classes = {
    critical: "border-red-500/50 bg-red-950/50 text-red-200",
    high: "border-orange-500/50 bg-orange-950/40 text-orange-200",
    medium: "border-amber-500/50 bg-amber-950/40 text-amber-200",
    low: "border-sky-500/50 bg-sky-950/40 text-sky-200",
  };
  return classes[severity];
}

function ImportedRepositoryCard({ item, isSelected, onSelect }: { item: ImportedRepository; isSelected: boolean; onSelect: () => void }) {
  return (
    <li className={`flex flex-col gap-3 rounded-xl border px-3 py-3 transition-colors duration-150 sm:flex-row sm:items-center sm:justify-between ${isSelected ? "border-cyan-400/70 bg-cyan-950/30 shadow-sm shadow-cyan-950/40" : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-600 hover:bg-zinc-950"}`}>
      <div className="min-w-0">
        <p className="truncate font-mono text-sm font-semibold text-cyan-200" title={item.full_name}>{item.full_name}</p>
        <p className="mt-1 line-clamp-2 text-sm leading-5 text-zinc-400">{item.description || "No repository description was provided."}</p>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
          <span className="rounded bg-zinc-900 px-1.5 py-0.5 text-zinc-400">{item.language || "Language not specified"}</span>
          <span className="font-mono">{item.default_branch ? `branch: ${item.default_branch}` : "Branch not specified"}</span>
        </div>
      </div>
      <button type="button" onClick={onSelect} disabled={isSelected} aria-pressed={isSelected} className="inline-flex min-h-9 shrink-0 items-center justify-center self-start rounded-lg border border-cyan-400/50 bg-cyan-400/10 px-3 py-2 text-sm font-semibold text-cyan-100 transition-colors duration-150 hover:bg-cyan-400/20 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-zinc-900 sm:self-auto disabled:cursor-default disabled:border-cyan-400/70 disabled:bg-cyan-950/40 disabled:text-cyan-100">
        {isSelected ? "Selected" : "Open"}
      </button>
    </li>
  );
}

function repositoryFromList(item: ImportedRepository): Repository {
  return {
    id: item.id,
    name: item.name,
    github_url: item.github_url,
    description: item.description,
    default_branch: item.default_branch,
    owner: item.owner,
    stars: item.stars,
    forks: item.forks,
    primary_language: item.language,
    created_at: item.created_at,
  };
}

function sameGitHubRepository(first: string, second: string) {
  return normalizeGitHubRepositoryUrl(first) === normalizeGitHubRepositoryUrl(second);
}

function normalizeGitHubRepositoryUrl(value: string) {
  try {
    const url = new URL(value.trim());
    if (url.hostname.toLowerCase() !== "github.com") return value.trim().toLowerCase();
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length !== 2) return value.trim().toLowerCase();
    const [owner, repository] = parts;
    return `https://github.com/${owner}/${repository.replace(/\.git$/, "")}`.toLowerCase();
  } catch {
    return value.trim().toLowerCase();
  }
}

function QuestionAnswerCard({ item }: { item: RepositoryAnswer }) {
  return (
    <article className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/70 shadow-sm shadow-black/10">
      <div className="border-b border-zinc-800 bg-zinc-900/80 px-4 py-3">
        <p className="text-xs font-semibold tracking-wide text-cyan-300 uppercase">Question</p>
        <p className="mt-1 text-sm font-medium leading-6 text-zinc-100">{item.question}</p>
      </div>
      <div className="px-4 py-4">
        <p className="text-xs font-semibold tracking-wide text-emerald-300 uppercase">Answer</p>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-7 text-zinc-200">{item.answer}</p>
        <div className="mt-5 border-t border-zinc-800 pt-4">
          <p className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">Sources</p>
          {item.sources.length > 0 ? (
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {item.sources.map((source) => (
                <li key={source.chunk_id} className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 font-mono text-xs leading-5 text-cyan-200">
                  <span className="block break-all">{source.path}</span>
                  <span className="text-zinc-400">Lines {source.start_line}–{source.end_line} · chunk {source.chunk_id}</span>
                </li>
              ))}
            </ul>
          ) : <p className="mt-2 text-sm text-zinc-500">No source chunks were returned.</p>}
        </div>
      </div>
    </article>
  );
}

function Metadata({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/80 px-4 py-3">
      <dt className="text-xs font-medium tracking-wide text-zinc-500 uppercase">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-zinc-100" title={value}>{value}</dd>
    </div>
  );
}
