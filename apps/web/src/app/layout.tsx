import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Dubbing Studio",
  description: "Translate and dub creator videos",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <Script id="webkit-empty-ranges" strategy="beforeInteractive">
          {`(function () {
  // Safari media controls read an unqualified EmptyRanges after a <video> is
  // destroyed (WebKit bug 318284). That throws into the Next.js error overlay.
  if (typeof globalThis.EmptyRanges === "undefined") {
    globalThis.EmptyRanges = {
      length: 0,
      start: function () { return 0; },
      end: function () { return 0; }
    };
  }
  window.addEventListener("error", function (event) {
    var message = event.message || (event.error && event.error.message) || "";
    if (message.indexOf("EmptyRanges") === -1) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  });
})();`}
        </Script>
      </head>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers>
          <Shell>{children}</Shell>
        </Providers>
      </body>
    </html>
  );
}
