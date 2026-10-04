/**
 * Typed client for the `/v2/projects` control-plane endpoints (E62-S4).
 *
 * The UI never touches the State Store; the project root a session uses is
 * resolved server-side from the stored project, never sent by this client
 * for path resolution. Roots are sent only to register a project
 * (`open` / `init` / `create`), an administrative operation.
 */

import { requestJson } from "./api_ext";

/** One project (`backend/api/routers/projects_v2.py::ProjectV2`). */
export interface ProjectV2 {
  projectId: string;
  name: string;
  rootPath: string;
  active: boolean;
}

/** Response of `GET /v2/projects`. */
export interface ProjectListV2 {
  schemaVersion: string;
  items: ProjectV2[];
  activeProjectId: string | null;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

function post<T>(path: string, body?: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/**
 * List the caller's projects.
 *
 * @returns The projects and the active project id (or null when none).
 * @throws Error when the request fails.
 */
export function listProjectsV2(): Promise<ProjectListV2> {
  return requestJson<ProjectListV2>("v2/projects");
}

/**
 * Open an existing project (its `.autodev/` is validated) and activate it.
 *
 * @param root - Project root directory.
 * @returns The activated project.
 */
export function openProjectV2(root: string): Promise<ProjectV2> {
  return post<ProjectV2>("v2/projects/open", { root });
}

/**
 * Configure an existing directory as a project. Existing files are left
 * untouched and no run is started.
 *
 * @param root - Existing directory.
 * @param name - Optional project name.
 * @returns The activated project.
 */
export function initProjectV2(root: string, name?: string): Promise<ProjectV2> {
  return post<ProjectV2>("v2/projects/init", { root, name });
}

/**
 * Create a new directory and initialize it as a project.
 *
 * @param root - Directory to create (must not exist).
 * @param name - Optional project name.
 * @returns The activated project.
 */
export function createProjectV2(root: string, name?: string): Promise<ProjectV2> {
  return post<ProjectV2>("v2/projects/create", { root, name });
}

/**
 * Make a registered project the active one.
 *
 * @param projectId - Project to activate.
 * @returns The activated project.
 */
export function activateProjectV2(projectId: string): Promise<ProjectV2> {
  return post<ProjectV2>(`v2/projects/${encodeURIComponent(projectId)}/activate`);
}
