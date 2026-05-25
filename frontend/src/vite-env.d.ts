/// <reference types="vite/client" />

declare module 'page-flip' {
  export class PageFlip {
    constructor(element: HTMLElement, settings?: Record<string, unknown>);
    loadFromHTML(items: NodeListOf<Element> | HTMLElement[]): void;
    destroy(): void;
    on(event: string, callback: (e: unknown) => void): void;
    getCurrentPageIndex(): number;
    getOrientation(): 'portrait' | 'landscape';
  }
}
