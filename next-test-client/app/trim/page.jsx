"use client";

import { useState } from "react";
import Link from "next/link";

const TRIM_TO_PRESETS = ["1.20", "2.04", "2.28", "3.25"];

function extractFilename(path) {
  if (!path) {
    return "";
  }

  const parts = path.split(/[\\/]/g);
  return parts[parts.length - 1] || "";
}

function formatSeconds(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "n/a";
  }

  return `${value.toFixed(2)}s`;
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
      const requestedDuration =
        typeof payload.trim_to === "number"
          ? payload.trim_to - (typeof payload.trim_from === "number" ? payload.trim_from : 0)
          : null;

      setSuccessData({
        ...data,
        filename,
        requested_duration_seconds: requestedDuration,
        requested_trim_mode: trimMode,
        requested_trim_from: payload.trim_from ?? null,
        requested_trim_to: payload.trim_to ?? null
      });
    } catch (error) {
      setErrorMessage(error.message || "Request failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  const trimmedDuration =
    typeof successData?.trimmed_duration_seconds === "number"
      ? successData.trimmed_duration_seconds
      : null;
  const requestedDuration =
    typeof successData?.requested_duration_seconds === "number"
      ? successData.requested_duration_seconds
      : null;
  const durationDelta =
    trimmedDuration !== null && requestedDuration !== null
      ? trimmedDuration - requestedDuration
      : null;
  const resultVideoHref = successData?.filename
    ? `/api/download/${encodeURIComponent(successData.filename)}`
    : null;

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
        <div className="hint-panel">
          <strong>Frame-accurate short trims are enabled.</strong>
          <p>
            This page is meant to verify exact cuts like <code>1.20</code>,
            <code>2.04</code>, <code>2.28</code>, and <code>3.25</code> seconds.
            After a response comes back, the tester shows the requested duration,
            the actual output duration, and an inline video preview.
          </p>
        </div>

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

          {trimMode === "from_end" ? (
            <div className="preset-row">
              <span>Quick trim_to checks</span>
              <div className="chip-row">
                {TRIM_TO_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    className="chip-button"
                    onClick={() => setTrimTo(preset)}
                  >
                    {preset}s
                  </button>
                ))}
              </div>
            </div>
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
            <div className="result-grid">
              <div className="result-stat">
                <span>Original duration</span>
                <strong>{formatSeconds(successData.original_duration_seconds)}</strong>
              </div>
              <div className="result-stat">
                <span>Requested duration</span>
                <strong>{formatSeconds(requestedDuration)}</strong>
              </div>
              <div className="result-stat">
                <span>Actual output</span>
                <strong>{formatSeconds(trimmedDuration)}</strong>
              </div>
              <div className="result-stat">
                <span>Duration delta</span>
                <strong className={Math.abs(durationDelta ?? 0) <= 0.15 ? "delta-good" : "delta-warn"}>
                  {durationDelta === null ? "n/a" : `${durationDelta >= 0 ? "+" : ""}${durationDelta.toFixed(2)}s`}
                </strong>
              </div>
              <div className="result-stat">
                <span>Processing time</span>
                <strong>{formatSeconds(successData.processing_time_seconds)}</strong>
              </div>
              <div className="result-stat">
                <span>Delete after</span>
                <strong>{formatSeconds(successData.delete_after_seconds)}</strong>
              </div>
            </div>
            {resultVideoHref ? (
              <div className="result-video-shell">
                <video className="video-preview" controls preload="metadata" src={resultVideoHref} />
              </div>
            ) : null}
            {successData.filename ? (
              <a href={resultVideoHref}>
                Download trimmed video
              </a>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
