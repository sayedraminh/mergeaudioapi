const BASE_URL = process.env.MERGE_API_BASE_URL || "http://localhost:8090";

export async function GET(_request, { params }) {
  const filename = params?.filename;

  if (!filename) {
    return Response.json({ detail: "Missing filename" }, { status: 400 });
  }

  const upstreamUrl = `${BASE_URL}/download/${encodeURIComponent(filename)}`;

  try {
    const response = await fetch(upstreamUrl, { cache: "no-store" });

    if (!response.ok) {
      const detail = await response.text();
      return Response.json({ detail: detail || "Download failed" }, { status: response.status });
    }

    const headers = new Headers();
    headers.set("content-type", response.headers.get("content-type") || "video/mp4");
    headers.set(
      "content-disposition",
      response.headers.get("content-disposition") || `attachment; filename=\"${filename}\"`
    );

    return new Response(response.body, {
      status: 200,
      headers
    });
  } catch (error) {
    return Response.json(
      { detail: error.message || "Failed to proxy download" },
      { status: 500 }
    );
  }
}
