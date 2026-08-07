export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export async function apiFetch(path: string, init?: RequestInit) {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
}

export async function errorMessage(response: Response) {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : "请求未能完成";
  } catch {
    return "请求未能完成";
  }
}

