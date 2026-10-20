import { useEffect, useState } from "react";

export type Theme = "system" | "light" | "dark";
const storageKey = "lodex-console-theme";

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage can be unavailable in a restricted browser context.
  }
  return "system";
}

export function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#171717" : "#ffffff");
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const system = matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(theme);
    update();
    system.addEventListener("change", update);
    return () => system.removeEventListener("change", update);
  }, [theme]);

  function changeTheme(value: Theme) {
    setTheme(value);
    try {
      localStorage.setItem(storageKey, value);
    } catch {
      // The selection still works for this page when persistence is unavailable.
    }
  }
  return { theme, changeTheme };
}
