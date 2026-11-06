import { Component, computed, input, signal } from '@angular/core';
import { initials } from '../core/format';

@Component({
  selector: 'app-avatar',
  template: `
    @if (url() && !failed()) {
      <img [src]="url()" alt="" referrerpolicy="no-referrer" (error)="failed.set(true)" />
    } @else {
      <span aria-hidden="true">{{ letters() }}</span>
    }
  `,
  styles: `
    :host {
      align-items: center;
      background: var(--accent-soft);
      border-radius: 50%;
      color: var(--accent);
      display: inline-flex;
      flex: none;
      font-size: calc(var(--size, 36px) * 0.36);
      font-weight: 600;
      height: var(--size, 36px);
      justify-content: center;
      overflow: hidden;
      width: var(--size, 36px);
    }
    img { height: 100%; object-fit: cover; width: 100%; }
  `,
})
export class Avatar {
  readonly name = input.required<string>();
  readonly url = input<string | null>(null);
  protected readonly failed = signal(false);
  protected readonly letters = computed(() => initials(this.name()));
}
