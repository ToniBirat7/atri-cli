'use client';

import { useEffect, useState } from 'react';

export interface ToastMessage {
  id: string;
  message: string;
  type: 'error' | 'success' | 'info' | 'warning';
  duration?: number;
}

interface ToastProps {
  message: ToastMessage;
  onDismiss: (id: string) => void;
}

function ToastItem({ message, onDismiss }: ToastProps) {
  useEffect(() => {
    if (!message.duration) return;
    const timer = setTimeout(() => onDismiss(message.id), message.duration);
    return () => clearTimeout(timer);
  }, [message, onDismiss]);

  const colors: Record<string, { bg: string; text: string; icon: string }> = {
    error: {
      bg: 'bg-rose-500/90',
      text: 'text-white',
      icon: '⚠',
    },
    success: {
      bg: 'bg-emerald-500/90',
      text: 'text-white',
      icon: '✓',
    },
    info: {
      bg: 'bg-sky-500/90',
      text: 'text-white',
      icon: 'ℹ',
    },
    warning: {
      bg: 'bg-amber-500/90',
      text: 'text-white',
      icon: '⚡',
    },
  };

  const style = colors[message.type];

  return (
    <div
      className={`${style.bg} ${style.text} rounded-lg px-4 py-3 shadow-lg backdrop-blur-sm flex items-center gap-3 max-w-sm animate-in fade-in slide-in-from-bottom-4 duration-300`}
    >
      <span className="text-lg font-bold">{style.icon}</span>
      <p className="text-sm font-medium flex-1">{message.message}</p>
      <button
        onClick={() => onDismiss(message.id)}
        className="ml-2 opacity-70 hover:opacity-100 transition-opacity"
      >
        ✕
      </button>
    </div>
  );
}

interface ToastContainerProps {
  messages: ToastMessage[];
  onDismiss: (id: string) => void;
}

export function ToastContainer({ messages, onDismiss }: ToastContainerProps) {
  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2 pointer-events-none">
      {messages.map((msg) => (
        <div key={msg.id} className="pointer-events-auto">
          <ToastItem message={msg} onDismiss={onDismiss} />
        </div>
      ))}
    </div>
  );
}

export function useToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const addToast = (
    message: string,
    type: 'error' | 'success' | 'info' | 'warning' = 'info',
    duration = 4000,
  ) => {
    const id = crypto.randomUUID();
    const toast: ToastMessage = { id, message, type, duration };
    setToasts((prev) => [...prev, toast]);
    return id;
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const errorToast = (message: string, duration?: number) =>
    addToast(message, 'error', duration);
  const successToast = (message: string, duration?: number) =>
    addToast(message, 'success', duration);
  const infoToast = (message: string, duration?: number) =>
    addToast(message, 'info', duration);
  const warningToast = (message: string, duration?: number) =>
    addToast(message, 'warning', duration);

  return {
    toasts,
    addToast,
    removeToast,
    errorToast,
    successToast,
    infoToast,
    warningToast,
  };
}
