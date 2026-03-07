const BASE_URL = process.env.MERGE_API_BASE_URL || "http://localhost:8090";
const API_KEY = process.env.MERGE_API_KEY || "";

export async function POST(request) {
  try {
    const contentType = request.headers.get("content-type") || "";
    const upstreamHeaders = API_KEY ? { "X-API-Key": API_KEY } : {};
    let body;

    if (contentType.includes("multipart/form-data")) {
      body = await request.formData();
    } else {
      const payload = await request.json();
      upstreamHeaders["Content-Type"] = "application/json";
      body = JSON.stringify(payload);
    }

    const response = await fetch(`${BASE_URL}/extract-fifth-frame`, {
      method: "POST",
      headers: upstreamHeaders,
      body,
      cache: "no-store"
    });

    if (!response.ok) {
      const contentType = response.headers.get("content-type") || "";

      if (contentType.includes("application/json")) {
        const data = await response.json();
        return Response.json(data, { status: response.status });
      }

      return Response.json(
        { detail: await response.text() || "Failed to extract the fifth frame" },
        { status: response.status }
      );
    }

    const responseHeaders = new Headers();
    responseHeaders.set("content-type", response.headers.get("content-type") || "image/png");
    responseHeaders.set(
      "content-disposition",
      response.headers.get("content-disposition") || 'attachment; filename="frame_5.png"'
    );

    return new Response(response.body, {
      status: 200,
      headers: responseHeaders
    });
  } catch (error) {
    return Response.json(
      { detail: error.message || "Failed to reach merge API" },
      { status: 500 }
    );
  }
}
