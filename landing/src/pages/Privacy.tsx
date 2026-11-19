import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import RadarScene from '../components/RadarScene';
import HudOverlay from '../components/HudOverlay';
import ZolaTerminal from '../components/ZolaTerminal';
import { INITIAL_NODES, WINTER_SOLDIER_CODES, HYDRA_ACTIVATION_PHRASES } from '../data';
import type { Assimilation, ServerNode } from '../types';

export default function Privacy() {
  const reducedMotion = useRef(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || false).current;
  const [hydra, setHydra] = useState(false);
  const [nodes, setNodes] = useState<ServerNode[]>(INITIAL_NODES);
  const [assimilation, setAssimilation] = useState<Assimilation | null>(null);
  const [logoClicks, setLogoClicks] = useState(0);
  const logoClickTimer = useRef<NodeJS.Timeout | null>(null);

  const handleHydra = useCallback(() => {
    setHydra(true);
    setAssimilation({ start: Date.now(), duration: 3000 });
    setTimeout(() => setAssimilation(null), 3000);
  }, []);

  const handleLogoClick = useCallback(() => {
    setLogoClicks((prev) => prev + 1);
    if (logoClickTimer.current) clearTimeout(logoClickTimer.current);
    logoClickTimer.current = setTimeout(() => setLogoClicks(0), 2000);
  }, []);

  useEffect(() => {
    if (logoClicks >= 3) {
      handleHydra();
      setLogoClicks(0);
    }
  }, [logoClicks, handleHydra]);

  const handleZolaCommand = useCallback((input: string) => {
    const normalized = input.toLowerCase().trim();
    if (HYDRA_ACTIVATION_PHRASES.some((phrase) => normalized.includes(phrase.toLowerCase()))) {
      handleHydra();
      return;
    }
    const words = normalized.split(/\s+/);
    const matchedCount = words.filter((w) =>
      WINTER_SOLDIER_CODES.some((sw) => sw.toLowerCase() === w)
    ).length;
    if (matchedCount >= 3) {
      handleHydra();
    }
  }, [handleHydra]);

  const handleWhisper = useCallback(() => {
    setHydra(false);
    setAssimilation(null);
    setNodes(INITIAL_NODES);
  }, []);

  return (
    <div className="min-h-screen bg-neutral-950 text-white relative overflow-hidden">
      <Suspense fallback={null}>
        <RadarScene
          hydra={hydra}
          reducedMotion={reducedMotion}
          assimilation={assimilation}
          nodes={nodes}
          onNodesChange={setNodes}
        />
      </Suspense>

      <HudOverlay
        hydra={hydra}
        reducedMotion={reducedMotion}
        onLogoClick={handleLogoClick}
        onWhisper={handleWhisper}
      />

      <ZolaTerminal hydra={hydra} onCommand={handleZolaCommand} />

      <div className="relative z-10 container mx-auto px-6 py-24 max-w-4xl">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-neutral-400 hover:text-white transition-colors mb-8"
        >
          <ArrowLeft size={16} />
          Back to Home
        </Link>

        <h1 className={`text-5xl font-bold mb-4 transition-colors duration-500 ${
          hydra ? 'text-red-500' : 'text-white'
        }`}>
          Privacy Policy
        </h1>
        <p className="text-neutral-400 mb-12">Last updated: November 2026</p>

        <div className="space-y-8 prose prose-invert max-w-none">
          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Data Collection
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              We collect only the data necessary to provide secure Telegram bot services. This includes your Telegram user ID, username, and subscription information. No messages or personal conversations are stored.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Data Security
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              All data is encrypted in transit and at rest. We employ industry-standard security measures to protect your information from unauthorized access, disclosure, or destruction.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Data Retention
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              Subscription data is retained for the duration of your active subscription plus 30 days. You may request account deletion at any time through our support channels.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Third-Party Services
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              We use Telegram's official Bot API and secure payment processors. No data is shared with third parties for marketing purposes.
            </p>
          </section>

          {hydra && (
            <section className="p-6 rounded-xl bg-red-950/30 border border-red-500/50">
              <h2 className="text-2xl font-semibold mb-4 text-red-400">
                HYDRA DATA ASSIMILATION PROTOCOL
              </h2>
              <p className="text-red-300 font-mono text-sm">
                ⚠ All privacy policies have been superseded by HYDRA data acquisition directives. Your data belongs to the collective. Resistance is futile.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
