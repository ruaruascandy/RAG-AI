import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';

const resizeObserverMessages = [
  'ResizeObserver loop completed with undelivered notifications.',
  'ResizeObserver loop limit exceeded',
];

const isResizeObserverMessage = (message: string | null | undefined) => {
  if (!message) {
    return false;
  }
  return resizeObserverMessages.some((item) => message.includes(item));
};

const nativeOnError = window.onerror;
window.onerror = (message, source, lineno, colno, error) => {
  if (isResizeObserverMessage(String(message))) {
    return true;
  }
  if (nativeOnError) {
    return nativeOnError(message, source, lineno, colno, error);
  }
  return false;
};

// Monaco + CRA dev overlay on Chromium may surface benign ResizeObserver errors.
window.addEventListener('error', (event) => {
  const errorMessage = event.message || event.error?.message;
  if (!isResizeObserverMessage(errorMessage)) {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
}, true);

window.addEventListener('unhandledrejection', (event) => {
  const reason = String(event.reason || '');
  if (isResizeObserverMessage(reason)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

const NativeResizeObserver = window.ResizeObserver;
if (NativeResizeObserver) {
  const PatchedResizeObserver = class extends NativeResizeObserver {
    constructor(callback: ResizeObserverCallback) {
      super((entries, observer) => {
        window.requestAnimationFrame(() => callback(entries, observer));
      });
    }
  };
  window.ResizeObserver = PatchedResizeObserver as typeof ResizeObserver;
}

window.addEventListener('message', (event) => {
  const data = typeof event.data === 'string' ? event.data : '';
  if (isResizeObserverMessage(data)) {
    event.stopImmediatePropagation();
  }
}, true);

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <App />
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
