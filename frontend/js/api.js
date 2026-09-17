// 所有网络交互集中于此，后续可替换为带鉴权的 API 客户端。
export async function request(path, payload) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(path, {
      signal: controller.signal,
      ...(payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
    return data;
  } finally { clearTimeout(timer); }
}
export const api = {
  catalog: () => request('/api/catalog'),
  config: () => request('/api/config'),
  simulate: settings => request('/api/simulate', settings),
  explain: settings => request('/api/analysis/explain', settings),
};
