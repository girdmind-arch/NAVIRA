import { useRef } from "react";
import { BrandMark, GirlIllustration, Icon } from "../components/ui";

const features = [
  { icon: "route", title: "Route Planner", text: "Compare car, motorcycle and walking routes with traffic, weather and local context, and see what the evidence can and cannot say." },
  { icon: "compass", title: "Journey Companion", text: "Follow your chosen route with live GPS. If you stop for five minutes, NAVIRA checks that you are safe." },
  { icon: "bell", title: "Automatic SOS", text: "No answer to three safety checks, or a tap on I Need Help, starts SOS with a live location link for your trusted contacts." },
  { icon: "shield", title: "Location Sharing", text: "Share a private, expiring location link with people you choose, and keep your trusted contacts in one place." },
  { icon: "pin", title: "Nearby Facilities", text: "Find mapped police stations and hospitals around the places on your route." },
  { icon: "report", title: "Community Reports", text: "Read and add short local reports about lighting, crowding and other conditions." },
];

const steps = [
  { title: "Plan", text: "Search your start and destination and compare the routes NAVIRA finds." },
  { title: "Go", text: "Pick a route; Journey Companion starts and follows your progress." },
  { title: "Stay connected", text: "Safety checks, SOS and live location keep trusted people close." },
];

/** First screen for signed-out visitors: a glass landing page in the GridNova style. */
export default function Onboarding({ onGetStarted, theme, headerActions = null, showSyntheticDemo = false, onSyntheticDemo }) {
  const featuresRef = useRef(null);

  return <main className="onboarding-page glass-landing">
    <header className="glass-landing__header">
      <div className="onboarding-brand glass-landing__brand" aria-label="NAVIRA">
        <BrandMark size={40} className="onboarding-brand__mark"/>
        <span className="glass-landing__brand-copy">
          <strong>NAVIRA</strong>
          <span>Safer steps. Brighter tomorrows.</span>
        </span>
      </div>
      <div className="glass-landing__actions">{headerActions}</div>
    </header>

    <section className="landing-hero glass-landing__hero" aria-labelledby="landing-hero-title">
      <div className="glass-landing__hero-copy">
        <span className="glass-landing__chip"><Icon name="sparkle" size={14}/> Journey safety · Delhi NCT</span>
        <h1 id="landing-hero-title">Move through your city with people you trust close by.</h1>
        <p>Plan routes with clear context, let Journey Companion watch over your trip, and share your live location only when you choose.</p>
        <div className="glass-landing__cta">
          <button className="button button--primary onboarding-start" type="button" onClick={onGetStarted}>
            Get Started <Icon name="arrow" size={18}/>
          </button>
          <button className="button glass-landing__ghost" type="button" onClick={() => featuresRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            See what NAVIRA does
          </button>
        </div>
        {showSyntheticDemo && <button className="onboarding-demo-link" type="button" onClick={onSyntheticDemo}>Open local synthetic route demo</button>}
      </div>
      <div className="glass-landing__preview">
        <div className="onboarding-art">
          <GirlIllustration theme={theme} alt="A girl walking along a winding path through a soft pink city landscape"/>
        </div>
        <ul className="glass-landing__badges" aria-label="Included tools">
          <li><Icon name="compass" size={16}/> Safety checks on the move</li>
          <li><Icon name="pin" size={16}/> Live location link</li>
          <li><Icon name="user" size={16}/> Trusted contacts</li>
        </ul>
      </div>
    </section>

    <section className="glass-landing__section" ref={featuresRef} aria-labelledby="landing-features-title">
      <p className="eyebrow">WHAT YOU GET</p>
      <h2 id="landing-features-title">Everything for the journey, in one place</h2>
      <div className="glass-landing__grid">
        {features.map((feature) => <article className="panel glass-landing__card" key={feature.title}>
          <span className="soft-icon"><Icon name={feature.icon} size={20}/></span>
          <h3>{feature.title}</h3>
          <p>{feature.text}</p>
        </article>)}
      </div>
    </section>

    <section className="glass-landing__section" aria-labelledby="landing-steps-title">
      <p className="eyebrow">HOW IT WORKS</p>
      <h2 id="landing-steps-title">Three steps, start to finish</h2>
      <ol className="glass-landing__steps">
        {steps.map((step, index) => <li className="panel" key={step.title}><span className="glass-landing__step-number">{index + 1}</span><h3>{step.title}</h3><p>{step.text}</p></li>)}
      </ol>
    </section>

    <section className="panel glass-landing__closing">
      <div>
        <h2>Ready when you are</h2>
        <p>NAVIRA gives you journey awareness tools. It does not dispatch emergency services; in an emergency in India, call 112.</p>
      </div>
      <button className="button button--primary" type="button" onClick={onGetStarted}>Sign in or create an account <Icon name="arrow" size={16}/></button>
    </section>

    <footer className="glass-landing__footer">
      <span>© NAVIRA · Journey awareness</span>
      <span>Plan thoughtfully. Stay connected.</span>
    </footer>
  </main>;
}
