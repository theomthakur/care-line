import "@testing-library/jest-dom/vitest";

// jsdom has no layout: stub the scroll APIs the console calls.
Element.prototype.scrollTo = (() => {}) as typeof Element.prototype.scrollTo;
Element.prototype.scrollIntoView = (() => {}) as typeof Element.prototype.scrollIntoView;
