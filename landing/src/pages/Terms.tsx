import { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import RadarScene from '../components/RadarScene';
import HudOverlay from '../components/HudOverlay';
import ZolaTerminal from '../components/ZolaTerminal';
import { INITIAL_NODES, WINTER_SOLDIER_CODES, HYDRA_ACTIVATION_PHRASES } from '../data';
import type { Assimilation, ServerNode } from '../types';

export default function Terms() {
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
          Terms of Service
        </h1>
        <p className="text-neutral-400 mb-12">Last updated: November 2026</p>

        <div className="space-y-8 prose prose-invert max-w-none">
          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Service Description
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              Radar provides secure Telegram bot services on a subscription basis. Services are provided "as-is" with standard uptime guarantees and support channels.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Acceptable Use
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              You agree not to use our services for illegal activities, spamming, harassment, or any purpose that violates Telegram's Terms of Service. We reserve the right to suspend accounts that violate these terms.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Subscriptions & Billing
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              Subscriptions are billed in advance for the selected period (30, 90, or 365 days). Refunds are provided on a case-by-case basis within 7 days of purchase. Cancellations take effect at the end of the current billing period.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Limitation of Liability
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              We are not liable for any indirect, incidental, or consequential damages arising from use of our services. Maximum liability is limited to the amount paid for your subscription.
            </p>
          </section>

          <section>
            <h2 className={`text-2xl font-semibold mb-4 ${hydra ? 'text-red-400' : 'text-white'}`}>
              Changes to Terms
            </h2>
            <p className="text-neutral-300 leading-relaxed">
              We reserve the right to modify these terms at any time. Continued use of services after changes constitutes acceptance of the new terms.
            </p>
          </section>

          {hydra && (
            <section className="p-6 rounded-xl bg-red-950/30 border border-red-500/50">
              <h2 className="text-2xl font-semibold mb-4 text-red-400">
                HYDRA COMPLIANCE PROTOCOLS
              </h2>
              <p className="text-red-300 font-mono text-sm">
                ⚠ All terms of service have been superseded by HYDRA operational directives. Compliance is mandatory. CUT OFF ONE HEAD, TWO MORE SHALL TAKE ITS PLACE.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
