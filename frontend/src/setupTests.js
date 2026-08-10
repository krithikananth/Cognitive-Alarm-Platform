import '@testing-library/jest-dom';

// jsdom has no ResizeObserver; recharts' ResponsiveContainer requires one.
if (typeof global.ResizeObserver === 'undefined') {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
