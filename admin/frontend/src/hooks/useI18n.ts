import { useState, useCallback } from "react";
import { zh } from "../i18n/zh";
import { en } from "../i18n/en";

const translations = { zh, en } as const;
export type Lang = keyof typeof translations;

export function useI18n() {
  const [lang, setLangState] = useState<Lang>(
    (localStorage.getItem("admin_lang") as Lang) || "zh"
  );
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem("admin_lang", l);
    setLangState(l);
  }, []);
  return { t: translations[lang], lang, setLang };
}
