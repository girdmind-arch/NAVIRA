import { useEffect, useState } from "react";
import { Icon } from "./ui";

const PRIMARY = [
  { id: "home", label: "Home", icon: "home" },
  { id: "routes", label: "Routes", icon: "route" },
  { id: "journey", label: "Journey", icon: "compass" },
  { id: "safety", label: "Share", icon: "shield" },
];

/** Phone and tablet navigation: four main pages plus a "More" sheet for the rest. */
export default function BottomNav({ page, pages, onNavigate }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const morePages = pages.filter((item) => !PRIMARY.some((primary) => primary.id === item.id));
  const moreActive = morePages.some((item) => item.id === page);

  useEffect(() => {
    if (!moreOpen) return undefined;
    const onKey = (event) => { if (event.key === "Escape") setMoreOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [moreOpen]);

  function go(event, id) {
    event.preventDefault();
    setMoreOpen(false);
    onNavigate(id);
  }

  return <>
    <nav className="bottom-nav" aria-label="Quick navigation">
      {PRIMARY.map((item) => <a key={item.id} href={"#/" + item.id} className={page === item.id ? "bottom-nav__item is-active" : "bottom-nav__item"} aria-current={page === item.id ? "page" : undefined} onClick={(event) => go(event, item.id)}>
        <Icon name={item.icon} size={22}/><span>{item.label}</span>
      </a>)}
      <button type="button" className={moreActive ? "bottom-nav__item is-active" : "bottom-nav__item"} aria-haspopup="dialog" aria-expanded={moreOpen} onClick={() => setMoreOpen(true)}>
        <Icon name="more" size={22}/><span>More</span>
      </button>
    </nav>
    {moreOpen && <div className="more-sheet" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setMoreOpen(false); }}>
      <section className="more-sheet__panel" role="dialog" aria-modal="true" aria-label="More pages">
        <div className="more-sheet__grip"/>
        <p className="more-sheet__title">More</p>
        {morePages.map((item) => <a key={item.id} href={"#/" + item.id} className={page === item.id ? "more-sheet__link is-active" : "more-sheet__link"} onClick={(event) => go(event, item.id)}>
          <Icon name={item.icon} size={20}/>{item.label}
        </a>)}
      </section>
    </div>}
  </>;
}
