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

export default function MergePage() {
  const [videoUrls, setVideoUrls] = useState(["", ""]);
  const [audioUrl, setAudioUrl] = useState("");
  const [outputFilename, setOutputFilename] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successData, setSuccessData] = useState(null);

  function updateVideoUrl(index, value) {
    setVideoUrls((prev) => {
      const next = [...prev];
      next[index] = value;
      return next;
    });
  }

  function addVideoField() {
    setVideoUrls((prev) => [...prev, ""]);
  }

  function removeVideoField(index) {
    if (videoUrls.length <= 1) return;
    setVideoUrls((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessData(null);

    const urls = videoUrls.map((u) => u.trim()).filter(Boolean);

    if (urls.length === 0) {
      setErrorMessage("At least one video URL is required.");
      setIsSubmitting(false);
      return;
    }

    if (!audioUrl.trim()) {
      setErrorMessage("Audio URL is required.");
      setIsSubmitting(false);
      return;
    }

    const payload = {
      video_urls: urls,
      audio_url: audioUrl.trim(),
      output_filename: outputFilename.trim() || undefined
    };

    try {
      const response = await fetch("/api/merge", {
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
          <span className="nav-active">Merge Tester</span>
          <Link href="/trim">Trim Tester</Link>
        </nav>

        <h1>Video Merge Tester</h1>
        <p>
          Concatenate video clips and overlay an audio track. Proxies to the FastAPI
          <code> /merge </code>
          endpoint.
        </p>

        <form onSubmit={handleSubmit} className="form">
          {videoUrls.map((url, index) => (
            <label key={index}>
              Video URL {index + 1}
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  type="url"
                  required
                  value={url}
                  onChange={(event) => updateVideoUrl(index, event.target.value)}
                  placeholder={`https://.../video${index + 1}.mp4`}
                  style={{ flex: 1 }}
                />
                {videoUrls.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => removeVideoField(index)}
                    className="btn-secondary"
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            </label>
          ))}

          <button type="button" onClick={addVideoField} className="btn-secondary">
            + Add another video
          </button>

          <label>
            Audio URL
            <input
              type="url"
              required
              value={audioUrl}
              onChange={(event) => setAudioUrl(event.target.value)}
              placeholder="https://.../song.mp3"
            />
          </label>

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="merged_output.mp4"
            />
          </label>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Processing..." : "Merge Videos"}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}

        {successData ? (
          <div className="result">
            <p>{successData.message}</p>
            <p>Processing time: {successData.processing_time_seconds ?? "n/a"}s</p>
            <p>Delete after: {successData.delete_after_seconds}s</p>
            {successData.filename ? (
              <a href={`/api/download/${encodeURIComponent(successData.filename)}`}>
                Download merged video
              </a>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
