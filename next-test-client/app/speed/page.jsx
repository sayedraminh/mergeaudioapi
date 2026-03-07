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

export default function SpeedPage() {
  const [videoUrl, setVideoUrl] = useState("");
  const [speed, setSpeed] = useState("1.3");
  const [outputFilename, setOutputFilename] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successData, setSuccessData] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessData(null);

    const parsedSpeed = Number(speed);
    if (Number.isNaN(parsedSpeed) || parsedSpeed <= 0) {
      setErrorMessage("Speed must be a number greater than 0 (for example 1.3 or 0.3).");
      setIsSubmitting(false);
      return;
    }

    const payload = {
      video_url: videoUrl.trim(),
      speed: parsedSpeed,
      output_filename: outputFilename.trim() || undefined
    };

    try {
      const response = await fetch("/api/speed", {
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
          <Link href="/reverse">Reverse Tester</Link>
          <span className="nav-active">Speed Tester</span>
          <Link href="/extract-fifth-frame">Frame Tester</Link>
        </nav>

        <h1>Speed/Slow Video Tester</h1>
        <p>
          Change video playback speed by URL and factor. Proxies to the FastAPI
          <code> /speed </code>
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
            Speed Factor
            <input
              type="number"
              step="any"
              min="0.000001"
              required
              value={speed}
              onChange={(event) => setSpeed(event.target.value)}
              placeholder="1.3 (faster) or 0.3 (slower)"
            />
            <small>Use values above 1.0 to speed up, below 1.0 to slow down.</small>
          </label>

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="speed_changed_output.mp4"
            />
          </label>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Processing..." : "Apply Speed Change"}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}

        {successData ? (
          <div className="result">
            <p>{successData.message}</p>
            <p>Speed factor: {successData.speed}x</p>
            <p>Original duration: {successData.original_duration_seconds}s</p>
            <p>Result duration: {successData.transformed_duration_seconds}s</p>
            <p>Processing time: {successData.processing_time_seconds ?? "n/a"}s</p>
            <p>Delete after: {successData.delete_after_seconds}s</p>
            {successData.filename ? (
              <a href={`/api/download/${encodeURIComponent(successData.filename)}`}>
                Download speed-adjusted video
              </a>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
