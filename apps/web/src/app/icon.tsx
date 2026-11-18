import { ImageResponse } from "next/og";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    <div style={{
      display: "flex", width: "100%", height: "100%", background: "#173a58", borderRadius: 13,
      alignItems: "flex-end", justifyContent: "center", paddingBottom: 15, gap: 5,
    }}>
      {[13, 22, 31].map((height, index) => <span key={height} style={{
        width: 7, height, borderRadius: 1, background: index === 2 ? "#8ac2aa" : "#eff6f9",
      }}/>)}
    </div>, size,
  );
}
