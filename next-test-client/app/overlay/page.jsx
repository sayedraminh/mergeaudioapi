"use client";

import { useState } from "react";
import Link from "next/link";

function extractFilename(path) {
  if (!path) return "";
  const parts = path.split(/[\\/]/g);
  return parts[parts.length - 1] || "";
}

function optionalPositiveNumber(value) {
  return value.trim() ? Number(value) : undefined;
}

export default function OverlayPage() {
  const [baseVideoUrl, setBaseVideoUrl] = useState("");
  const [overlayVideoUrl, setOverlayVideoUrl] = useState("");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  const [overlayWidth, setOverlayWidth] = useState("");
  const [overlayHeight, setOverlayHeight] = useState("");
  const [outputFilename, setOutputFilename] = useState("layered-video.mp4");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successData, setSuccessData] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessData(null);

    const width = optionalPositiveNumber(overlayWidth);
    const height = optionalPositiveNumber(overlayHeight);
    if ((width !== undefined && width <= 0) || (height !== undefined && height <= 0)) {
      setErrorMessage("Layer width and height must be greater than zero.");
      setIsSubmitting(false);
      return;
    }

    const payload = {
      base_video_url: baseVideoUrl.trim(),
      overlay_video_url: overlayVideoUrl.trim(),
      x: Number(x),
      y: Number(y),
      overlay_width: width,
      overlay_height: height,
      output_filename: outputFilename.trim() || undefined
    };

    try {
      const response = await fetch("/api/overlay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = data?.detail || "Unknown error";
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      setSuccessData({ ...data, filename: extractFilename(data.output_path) });
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
          <span className="nav-active">Overlay Tester</span>
          <Link href="/trim">Trim Tester</Link>
          <Link href="/reverse">Reverse Tester</Link>
          <Link href="/speed">Speed Tester</Link>
          <Link href="/extract-fifth-frame">Frame Tester</Link>
        </nav>

        <h1>Video Layer Tester</h1>
        <p>
          Place a visual video layer over the user's original video. The result keeps
          the original video's dimensions, duration, and audio.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <label>
            Original (Base) Video URL
            <input
              type="url"
              required
              value={baseVideoUrl}
              onChange={(event) => setBaseVideoUrl(event.target.value)}
              placeholder="https://.../original.mp4"
            />
          </label>

          <label>
            Layer Video URL
            <input
              type="url"
              required
              value={overlayVideoUrl}
              onChange={(event) => setOverlayVideoUrl(event.target.value)}
              placeholder="https://.../layer.webm"
            />
            <small>
              Transparent WebM or MOV layers are supported. Leave both dimensions blank
              to match the layer canvas to the base video. Layer audio is ignored.
            </small>
          </label>

          <div className="result-grid">
            <label>
              X Position
              <input type="number" required value={x} onChange={(event) => setX(event.target.value)} />
            </label>
            <label>
              Y Position
              <input type="number" required value={y} onChange={(event) => setY(event.target.value)} />
            </label>
            <label>
              Layer Width (optional)
              <input
                type="number"
                min="1"
                value={overlayWidth}
                onChange={(event) => setOverlayWidth(event.target.value)}
                placeholder="Match base width"
              />
            </label>
            <label>
              Layer Height (optional)
              <input
                type="number"
                min="1"
                value={overlayHeight}
                onChange={(event) => setOverlayHeight(event.target.value)}
                placeholder="Match base height"
              />
            </label>
          </div>

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="layered-video.mp4"
            />
          </label>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Adding layer..." : "Add Video Layer"}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}
        {successData ? (
          <div className="result">
            <p>{successData.message}</p>
            <p>Base duration: {successData.base_duration_seconds}s</p>
            <p>Processing time: {successData.processing_time_seconds ?? "n/a"}s</p>
            {successData.filename ? (
              <a href={`/api/download/${encodeURIComponent(successData.filename)}`}>
                Download layered video
              </a>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
