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

export default function TrimPage() {
  const [videoUrl, setVideoUrl] = useState("");
  const [trimMode, setTrimMode] = useState("from_start");
  const [trimFrom, setTrimFrom] = useState("");
  const [trimTo, setTrimTo] = useState("");
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

    if (trimMode === "from_start") {
      if (!trimFrom.trim()) {
        setErrorMessage("Please enter a trim_from value (seconds to cut from the beginning).");
        setIsSubmitting(false);
        return;
      }
      payload.trim_from = Number(trimFrom);
      if (Number.isNaN(payload.trim_from) || payload.trim_from < 0) {
        setErrorMessage("trim_from must be a positive number.");
        setIsSubmitting(false);
        return;
      }
    } else if (trimMode === "from_end") {
      if (!trimTo.trim()) {
        setErrorMessage("Please enter a trim_to value (keep only the first N seconds).");
        setIsSubmitting(false);
        return;
      }
      payload.trim_to = Number(trimTo);
      if (Number.isNaN(payload.trim_to) || payload.trim_to <= 0) {
        setErrorMessage("trim_to must be a positive number.");
        setIsSubmitting(false);
        return;
      }
    } else if (trimMode === "range") {
      if (!trimFrom.trim() || !trimTo.trim()) {
        setErrorMessage("Both trim_from and trim_to are required for range mode.");
        setIsSubmitting(false);
        return;
      }
      payload.trim_from = Number(trimFrom);
      payload.trim_to = Number(trimTo);
      if (Number.isNaN(payload.trim_from) || Number.isNaN(payload.trim_to)) {
        setErrorMessage("Both values must be valid numbers.");
        setIsSubmitting(false);
        return;
      }
      if (payload.trim_from >= payload.trim_to) {
        setErrorMessage("trim_from must be less than trim_to.");
        setIsSubmitting(false);
        return;
      }
    }

    try {
      const response = await fetch("/api/trim", {
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
          <span className="nav-active">Trim Tester</span>
          <Link href="/reverse">Reverse Tester</Link>
          <Link href="/speed">Speed Tester</Link>
          <Link href="/extract-fifth-frame">Frame Tester</Link>
        </nav>

        <h1>Video Trim Tester</h1>
        <p>
          Trim a video clip by specifying where to cut. Proxies to the FastAPI
          <code> /trim </code>
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
            Trim Mode
            <select
              value={trimMode}
              onChange={(event) => setTrimMode(event.target.value)}
            >
              <option value="from_start">Cut from start (remove first N seconds)</option>
              <option value="from_end">Cut from end (keep first N seconds)</option>
              <option value="range">Extract range (from point A to point B)</option>
            </select>
          </label>

          {(trimMode === "from_start" || trimMode === "range") ? (
            <label>
              {trimMode === "from_start" ? "Cut first N seconds (trim_from)" : "Start point in seconds (trim_from)"}
              <input
                type="number"
                step="any"
                min="0"
                value={trimFrom}
                onChange={(event) => setTrimFrom(event.target.value)}
                placeholder="e.g. 1.07"
              />
              {trimMode === "from_start" ? (
                <small>Everything before this timestamp will be removed.</small>
              ) : (
                <small>The extracted segment starts here.</small>
              )}
            </label>
          ) : null}

          {(trimMode === "from_end" || trimMode === "range") ? (
            <label>
              {trimMode === "from_end" ? "Keep first N seconds (trim_to)" : "End point in seconds (trim_to)"}
              <input
                type="number"
                step="any"
                min="0"
                value={trimTo}
                onChange={(event) => setTrimTo(event.target.value)}
                placeholder="e.g. 10.5"
              />
              {trimMode === "from_end" ? (
                <small>Everything after this timestamp will be removed.</small>
              ) : (
                <small>The extracted segment ends here.</small>
              )}
            </label>
          ) : null}

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="trimmed_output.mp4"
            />
          </label>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Processing..." : "Trim Video"}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}

        {successData ? (
          <div className="result">
            <p>{successData.message}</p>
            <p>Original duration: {successData.original_duration_seconds}s</p>
            <p>Trimmed duration: {successData.trimmed_duration_seconds}s</p>
            <p>Processing time: {successData.processing_time_seconds ?? "n/a"}s</p>
            <p>Delete after: {successData.delete_after_seconds}s</p>
            {successData.filename ? (
              <a href={`/api/download/${encodeURIComponent(successData.filename)}`}>
                Download trimmed video
              </a>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
