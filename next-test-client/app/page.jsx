"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

const DEFAULT_BEATS = "4.20,7.20,10.20,12.26";
const DEFAULT_VIDEO_CUTS = "0,0";

function parseNumberList(input) {
  return input
    .split(/[\n,]/g)
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => Number(value));
}

function extractFilename(path) {
  if (!path) {
    return "";
  }

  const parts = path.split(/[\\/]/g);
  return parts[parts.length - 1] || "";
}

export default function Page() {
  const [video1Url, setVideo1Url] = useState("");
  const [video2Url, setVideo2Url] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const [beatsText, setBeatsText] = useState(DEFAULT_BEATS);
  const [videoCutsText, setVideoCutsText] = useState(DEFAULT_VIDEO_CUTS);
  const [outputFilename, setOutputFilename] = useState("beat_sync_test.mp4");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [successData, setSuccessData] = useState(null);

  const previewIntervals = useMemo(() => {
    const beats = parseNumberList(beatsText);

    if (beats.some((value) => Number.isNaN(value))) {
      return "Invalid beats";
    }

    let previous = 0;
    const intervals = [];
    for (const beat of beats) {
      intervals.push((beat - previous).toFixed(2));
      previous = beat;
    }
    return intervals.join(" / ");
  }, [beatsText]);

  async function handleSubmit(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    setSuccessData(null);

    const beats = parseNumberList(beatsText);
    const videoCuts = videoCutsText.trim() ? parseNumberList(videoCutsText) : undefined;

    if (beats.length === 0 || beats.some((value) => Number.isNaN(value))) {
      setErrorMessage("Beat timestamps must be a comma-separated list of numbers.");
      setIsSubmitting(false);
      return;
    }

    if (
      videoCuts &&
      (videoCuts.length === 0 || videoCuts.some((value) => Number.isNaN(value)))
    ) {
      setErrorMessage("Video cut starts must be numbers if provided.");
      setIsSubmitting(false);
      return;
    }

    const payload = {
      video_urls: [video1Url.trim(), video2Url.trim()],
      audio_url: audioUrl.trim(),
      beat_timestamps: beats,
      output_filename: outputFilename.trim() || undefined
    };

    if (videoCuts && videoCuts.length > 0) {
      payload.video_cut_starts = videoCuts;
    }

    try {
      const response = await fetch("/api/merge-beat-sync", {
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
          <span className="nav-active">Beat Sync Tester</span>
          <Link href="/merge">Merge Tester</Link>
          <Link href="/trim">Trim Tester</Link>
          <Link href="/reverse">Reverse Tester</Link>
          <Link href="/speed">Speed Tester</Link>
          <Link href="/extract-fifth-frame">Frame Tester</Link>
        </nav>

        <h1>Beat Sync Merge Tester</h1>
        <p>
          Sends requests to the local Next API route, which proxies to your FastAPI
          <code> /merge-beat-sync </code>
          endpoint.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <label>
            Video URL 1
            <input
              type="url"
              required
              value={video1Url}
              onChange={(event) => setVideo1Url(event.target.value)}
              placeholder="https://.../video1.mp4"
            />
          </label>

          <label>
            Video URL 2
            <input
              type="url"
              required
              value={video2Url}
              onChange={(event) => setVideo2Url(event.target.value)}
              placeholder="https://.../video2.mp4"
            />
          </label>

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
            Beat Timestamps (seconds, comma-separated)
            <textarea
              required
              value={beatsText}
              onChange={(event) => setBeatsText(event.target.value)}
              rows={3}
              placeholder="4.20,7.20,10.20,12.26"
            />
          </label>

          <label>
            Video Cut Starts (optional)
            <textarea
              value={videoCutsText}
              onChange={(event) => setVideoCutsText(event.target.value)}
              rows={2}
              placeholder="0,0"
            />
            <small>
              Use 2 numbers (one for each source clip) or one number per beat segment.
            </small>
          </label>

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="beat_sync_test.mp4"
            />
          </label>

          <div className="preview">Segment lengths preview: {previewIntervals}</div>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Processing..." : "Create Beat-Synced Video"}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}

        {successData ? (
          <div className="result">
            <p>{successData.message}</p>
            <p>Segments created: {successData.segments_created}</p>
            <p>Total duration: {successData.total_duration_seconds}s</p>
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
