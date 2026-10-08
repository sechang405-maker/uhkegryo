import "./globals.css";

export const metadata = {
  title: "UH케그려",
  description: "캐릭터 드로잉 레퍼런스 탐색",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
