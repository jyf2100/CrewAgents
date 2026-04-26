import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from "react";
import { zh } from "./zh";
import { en } from "./en";

const translations = { zh, en } as const;
type Lang = "zh" | "en";

interface I18nContextType {
  t: typeof zh;
  lang: Lang;
  setLang: (l: Lang) => void;
}

const I18nContext = createContext<I18nContextType>({
  t: zh,
  lang: "zh",
  setLang: () => {},
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(
    (localStorage.getItem("admin_lang") as Lang) || "zh"
  );
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem("admin_lang", l);
    setLangState(l);
  }, []);
  const value = useMemo(() => ({ t: translations[lang], lang, setLang }), [lang, setLang]);
  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  return useContext(I18nContext);
}
