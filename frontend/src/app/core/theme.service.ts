import { Injectable, signal } from '@angular/core';
import { ThemePreference } from './models';

const STORAGE_KEY = 'monetta-theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly media = matchMedia('(prefers-color-scheme: dark)');
  readonly preference = signal<ThemePreference>(this.stored());
  readonly resolved = signal<'light' | 'dark'>('light');

  constructor() {
    this.media.addEventListener('change', () => this.apply());
    this.apply();
  }

  set(preference: ThemePreference): void {
    this.preference.set(preference);
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      // Sem armazenamento local o tema ainda vale para esta visita.
    }
    this.apply();
  }

  private stored(): ThemePreference {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch {
      return 'system';
    }
  }

  private apply(): void {
    const pref = this.preference();
    const theme = pref === 'system' ? (this.media.matches ? 'dark' : 'light') : pref;
    document.documentElement.setAttribute('data-bs-theme', theme);
    this.resolved.set(theme);
  }
}
