import { Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../core/auth.service';
import { MOBILE_ITEMS, MORE_ITEMS, NAV_ITEMS } from '../core/navigation';
import { PurchaseForm } from '../shared/purchase-form';
import { TransactionForm } from '../shared/transaction-form';
import { Avatar } from './avatar';

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Avatar, PurchaseForm, TransactionForm],
  templateUrl: './shell.html',
  styleUrl: './shell.css',
})
export class Shell {
  protected readonly auth = inject(AuthService);
  protected readonly nav = NAV_ITEMS;
  protected readonly mobile = MOBILE_ITEMS;
  protected readonly more = MORE_ITEMS;
  protected readonly moreOpen = signal(false);
  protected readonly quickExpense = signal(false);
  protected readonly quickPurchase = signal(false);
  protected readonly exact = { exact: true };
}
