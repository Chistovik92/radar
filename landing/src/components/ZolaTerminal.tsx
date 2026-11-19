import { useEffect, useRef, useState } from 'react';
import { TerminalSquare } from 'lucide-react';
import { HYDRA_ACTIVATION_PHRASES, HYDRA_LOGS, NORMAL_LOGS, WINTER_SOLDIER_CODES } from '../data';

export default function ZolaTerminal({ hydra, onHydra }: { hydra: boolean; onHydra: () => void }) {
  const [lines, setLines] = useState<string[]>([
    '[BOOT] RADAR CORE :: public interface ready',
    '[MONITOR] awaiting source cycle',
  ]);
  const [command, setCommand] = useState('');
  const output = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const source = hydra ? HYDRA_LOGS : NORMAL_LOGS;
      const stamp = new Date().toLocaleTimeString('ru-RU', { hour12: false });
      setLines((current) => [...current.slice(-7), `${stamp} ${source[Math.floor(Math.random() * source.length)]}`]);
    }, hydra ? 1700 : 3200);
    return () => window.clearInterval(timer);
  }, [hydra]);

  useEffect(() => {
    output.current?.scrollTo({ top: output.current.scrollHeight, behavior: 'smooth' });
  }, [lines]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const normalized = command.trim().toLocaleLowerCase('ru-RU').replace(/[,;.!]/g, '').replace(/\s+/g, ' ');
    
    // Проверка полных фраз активации
    const isActivationPhrase = HYDRA_ACTIVATION_PHRASES.some(phrase => 
      normalized === phrase.toLocaleLowerCase('ru-RU')
    );
    
    // Проверка кодовых слов Зимнего Солдата (любое из списка активирует)
    const isWinterSoldierCode = WINTER_SOLDIER_CODES.some(code => 
      normalized === code.toLocaleLowerCase('ru-RU')
    );
    
    if (isActivationPhrase || isWinterSoldierCode) {
      onHydra();
      const responseMsg = isWinterSoldierCode 
        ? '[ZOLA] WINTER_SOLDIER_PROTOCOL :: CODE_17 CONFIRMED :: ASSET READY'
        : '[ZOLA] activation phrase accepted :: PROJECT INSIGHT';
      setLines((current) => [...current, responseMsg]);
    } else {
      setLines((current) => [...current, `> ${command}`, '[CORE] unknown command :: try /status']);
    }
    setCommand('');
  };

  return (
    <section className="terminal-shell" aria-label="Живой системный журнал">
      <div className="terminal-title">
        <TerminalSquare size={15} />
        <span>{hydra ? 'ZOLA_TERMINAL // SECURE CHANNEL' : 'RADAR_TERMINAL // LIVE'}</span>
        <i />
      </div>
      <div className="terminal-output" ref={output} aria-live="polite">
        {lines.map((line, index) => <code key={`${index}-${line}`}>{line}</code>)}
      </div>
      <form className="terminal-form" onSubmit={submit}>
        <label htmlFor="terminal-command">Команда</label>
        <span>›</span>
        <input
          id="terminal-command"
          value={command}
          onChange={(event) => setCommand(event.target.value)}
          placeholder="/status"
          autoComplete="off"
          spellCheck={false}
        />
      </form>
    </section>
  );
}
