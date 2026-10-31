import { BrandMark, GirlIllustration, Icon } from "../components/ui";

export default function Onboarding({ onGetStarted, theme, showSyntheticDemo = false, onSyntheticDemo }) {
  return <main className="onboarding-page">
    <header className="onboarding-brand" aria-label="NAVIRA">
      <BrandMark size={76} className="onboarding-brand__mark"/>
      <strong>NAVIRA</strong>
      <span>Safer steps. Brighter tomorrows.</span>
    </header>
    <div className="onboarding-art">
      <GirlIllustration theme={theme} alt="A girl walking along a winding path through a soft pink city landscape"/>
    </div>
    <button className="onboarding-start" type="button" onClick={onGetStarted}>
      Get Started <Icon name="arrow" size={23}/>
    </button>
    {showSyntheticDemo && <button className="onboarding-demo-link" type="button" onClick={onSyntheticDemo}>Open local synthetic route demo</button>}
  </main>;
}
