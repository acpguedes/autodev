// Small, pure URL helpers shared by the frontend API clients. Kept dependency-free
// and side-effect-free so they are trivially unit-testable.

export const stripTrailingSlash = (url: string): string => url.replace(/\/+$/, "");

export const ensureLeadingSlash = (path: string): string =>
  path.startsWith("/") ? path : `/${path}`;

export const joinUrl = (base: string, path: string): string => {
  const normalizedPath = ensureLeadingSlash(path);
  const normalizedBase = stripTrailingSlash(base);
  return normalizedBase ? `${normalizedBase}${normalizedPath}` : normalizedPath;
};
