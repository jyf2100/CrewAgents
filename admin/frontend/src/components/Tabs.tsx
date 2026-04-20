interface Tab {
  value: string;
  label: string;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onChange: (value: string) => void;
}

export function Tabs({ tabs, activeTab, onChange }: TabsProps) {
  return (
    <div className="flex gap-1 border-b border-border-subtle overflow-x-auto">
      {tabs.map((tab) => {
        const isActive = tab.value === activeTab;
        return (
          <button
            key={tab.value}
            onClick={() => onChange(tab.value)}
            className={`
              relative px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors
              ${
                isActive
                  ? "text-accent-pink"
                  : "text-text-secondary hover:text-text-primary"
              }
            `}
          >
            {tab.label}
            {isActive && (
              <span className="absolute bottom-0 left-0 right-0 h-[3px] bg-accent-pink rounded-t" />
            )}
          </button>
        );
      })}
    </div>
  );
}
