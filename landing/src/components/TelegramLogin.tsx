import { useEffect, useRef } from 'react';

export default function TelegramLogin({ botUsername }: { botUsername: string }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = container.current;
    if (!element || !botUsername) return;
    element.replaceChildren();
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.dataset.telegramLogin = botUsername;
    script.dataset.size = 'large';
    script.dataset.authUrl = '/auth';
    script.dataset.requestAccess = 'write';
    element.appendChild(script);
    return () => element.replaceChildren();
  }, [botUsername]);

  if (!botUsername) {
    return <p className="login-fallback">Укажите BotFather username и WEB_PUBLIC_URL, затем вход появится здесь.</p>;
  }
  return <div ref={container} className="telegram-login" aria-label="Вход через Telegram" />;
}
