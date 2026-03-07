const BASE_URL = process.env.MERGE_API_BASE_URL || "http://localhost:8090";
const API_KEY = process.env.MERGE_API_KEY || "";

export async function POST(request) {
  try {
    const payload = await request.json();

    const response = await fetch(`${BASE_URL}/reverse`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {})
      },
      body: JSON.stringify(payload),
      cache: "no-store"
    });

    const contentType = response.headers.get("content-type") || "";
    let data;

    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      data = { detail: await response.text() };
    }

    return Response.json(data, { status: response.status });
  } catch (error) {
    return Response.json(
      { detail: error.message || "Failed to reach merge API" },
      { status: 500 }
    );
  }
}
