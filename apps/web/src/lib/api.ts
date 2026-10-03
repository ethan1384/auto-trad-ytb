export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Project = {
  id: string;
  name: string;
  source_language: string;
  target_language: string;
  target_accent: string | null;
  voice_consent: boolean;
  include_subtitles: boolean;
  created_at: string;
};

export type JobStage = {
  id: string;
  name: string;
  position: number;
  status: string;
  attempt: number;
  detail: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
};

export type Artifact = {
  id: string;
  kind: string;
  storage_key: string;
  download_url: string | null;
  mime_type: string | null;
};

export type Job = {
  id: string;
  project_id: string;
  status: string;
  current_stage: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  stages: JobStage[];
};

function errorMessage(body: string, statusText: string): string {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) return parsed.detail;
  } catch {
    // Response body is not JSON.
  }
  if (body === "Load failed" || body === "Failed to fetch") {
    return "The API or upload storage could not be reached. Check that the backend is running.";
  }
  return body || statusText;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Request failed";
    throw new Error(errorMessage(message, message));
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(errorMessage(body, res.statusText));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  listProjects: () => request<Project[]>("/projects"),
  createProject: (payload: {
    name: string;
    source_language: string;
    target_language: string;
    target_accent?: string | null;
    voice_consent: boolean;
    include_subtitles: boolean;
  }) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateProject: (id: string, payload: { include_subtitles?: boolean; target_accent?: string | null }) =>
    request<Project>(`/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  uploadSource: async (projectId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    let res: Response;
    try {
      res = await fetch(`${API_URL}/projects/${projectId}/assets`, { method: "POST", body });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed";
      throw new Error(errorMessage(message, message));
    }
    if (!res.ok) {
      throw new Error(errorMessage(await res.text(), res.statusText));
    }
    return res.json() as Promise<{ id: string }>;
  },
  createUploadUrl: (projectId: string, filename: string, contentType: string) =>
    request<{ asset_id: string; upload_url: string; headers: Record<string, string> }>(
      `/projects/${projectId}/assets/upload-url`,
      {
        method: "POST",
        body: JSON.stringify({ filename, content_type: contentType }),
      }
    ),
  confirmAsset: (projectId: string, assetId: string) =>
    request(`/projects/${projectId}/assets/confirm`, {
      method: "POST",
      body: JSON.stringify({ asset_id: assetId }),
    }),
  createJob: (projectId: string, sourceAssetId?: string) =>
    request<Job>(`/projects/${projectId}/jobs`, {
      method: "POST",
      body: JSON.stringify(sourceAssetId ? { source_asset_id: sourceAssetId } : {}),
    }),
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  latestJob: (projectId: string) => request<Job | null>(`/projects/${projectId}/jobs/latest`),
  listArtifacts: (projectId: string) => request<Artifact[]>(`/projects/${projectId}/artifacts`),
};
