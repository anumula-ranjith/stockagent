import { ImageResponse } from "next/og";

export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    <div style={{
      display: "flex", width: "100%", height: "100%", background: "#173a58", borderRadius: 13,
      alignItems: "center", justifyContent: "center", color: "#f0f5f7", fontSize: 49,
      fontFamily: "Georgia", fontWeight: 400,
    }}>Q</div>, size,
  );
}
