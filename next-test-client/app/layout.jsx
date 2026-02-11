import "./globals.css";

export const metadata = {
  title: "Beat Sync Merge Tester",
  description: "Test client for /merge-beat-sync endpoint"
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
