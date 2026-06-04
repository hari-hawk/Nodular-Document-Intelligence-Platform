"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { LoginScreen } from "@/components/login-screen";
import { isAuthed } from "@/lib/api";

/**
 * Root route: if the browser has credentials stored, redirect straight
 * to /workspace. Otherwise show the login form.
 *
 * Why the loading flicker: we check localStorage CLIENT-side which
 * means the first render is always pre-auth. A future cookie-based
 * server check would eliminate the flicker but isn't worth the moving
 * pieces for an internal admin UI.
 */
export default function HomePage() {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (isAuthed()) {
      router.replace("/workspace");
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) return null;
  return <LoginScreen />;
}
