"use client";

import { useEffect } from "react";
import { useParams } from "next/navigation";

// Deprecated: character details now live entirely in the admin panel.
// This page just redirects to /admin?id={id} (the /admin route is rewritten to the
// backend admin panel in next.config). Single place to view characters.
export default function RobotDetailRedirect() {
  const params = useParams();
  useEffect(() => {
    const id = params?.id as string | undefined;
    if (id) window.location.replace(`/admin?id=${id}`);
  }, [params]);

  return (
    <div
      style={{
        minHeight: "60vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#888",
        fontSize: 14,
      }}
    >
      正在跳转到管理后台…
    </div>
  );
}
