import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

const title = "光伏智库｜分布式光伏知识问答";
const description = "基于政策、标准与设备资料的可追溯分布式光伏知识问答平台。";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const image = `${protocol}://${host}/og.png`;
  return {
    title,
    description,
    openGraph: { title, description, type: "website", locale: "zh_CN", images: [{ url: image, width: 1732, height: 908, alt: "光伏智库" }] },
    twitter: { card: "summary_large_image", title, description, images: [image] },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
