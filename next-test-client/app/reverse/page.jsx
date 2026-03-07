"use client";

import { useState } from "react";
import Link from "next/link";

function extractFilename(path) {
  if (!path) {
    return "";
  }

  const parts = path.split(/[\\/]/g);
  return parts[parts.length - 1] || "";
}

export default function ReversePage() {
  const [videoUrl, setVideoUrl] = useState("");
  const [outputFilename, setOutputFilename] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successData, setSuccessData] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessData(null);

    const payload = {
      video_url: videoUrl.trim(),
      output_filename: outputFilename.trim() || undefined
    };

    try {
      const response = await fetch("/api/reverse", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const data = await response.json();

      if (!response.ok) {
        const detail = data?.detail || "Unknown error";
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      const filename = extractFilename(data.output_path) || payload.output_filename || "";
      setSuccessData({ ...data, filename });
    } catch (error) {
      setErrorMessage(error.message || "Request failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="container">
      <section className="card">
        <nav className="nav-links">
          <Link href="/">Beat Sync Tester</Link>
          <Link href="/merge">Merge Tester</Link>
          <Link href="/trim">Trim Tester</Link>
          <span className="nav-active">Reverse Tester</span>
          <Link href="/speed">Speed Tester</Link>
          <Link href="/extract-fifth-frame">Frame Tester</Link>
        </nav>

        <h1>Reverse Video Tester</h1>
        <p>
          Reverse an entire video by URL. Proxies to the FastAPI
          <code> /reverse </code>
          endpoint.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <label>
            Video URL
            <input
              type="url"
              required
              value={videoUrl}
              onChange={(event) => setVideoUrl(event.target.value)}
              placeholder="https://.../video.mp4"
            />
          </label>

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="reversed_output.mp4"
            />
          </label>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Processing..." : "Reverse Video"}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}

        {successData ? (
          <div className="result">
            <p>{successData.message}</p>
            <p>Original duration: {successData.original_duration_seconds}s</p>
            <p>Result duration: {successData.transformed_duration_seconds}s</p>
            <p>Processing time: {successData.processing_time_seconds ?? "n/a"}s</p>
            <p>Delete after: {successData.delete_after_seconds}s</p>
            {successData.filename ? (
              <a href={`/api/download/${encodeURIComponent(successData.filename)}`}>
                Download reversed video
              </a>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
