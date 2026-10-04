import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      setAuth: (user, token) => set({ user, token }),
      logout: () => set({ user: null, token: null }),
      isAdmin: () => get().user?.role === 'admin',
    }),
    {
      name: 'auth-storage',
    }
  )
);

export const useCartStore = create(
  persist(
    (set, get) => ({
      items: [],
      // Add item with optional renewal info (physical items merge into one line with a quantity)
      addItem: (item) => set((state) => {
        if (item.item_type === 'physical') {
          const existing = state.items.find((i) => i.item_type === 'physical' && i.product_id === item.product_id);
          if (existing) {
            return { items: state.items.map((i) => i === existing ? { ...i, quantity: (i.quantity || 1) + (item.quantity || 1) } : i) };
          }
          return { items: [...state.items, { ...item, quantity: item.quantity || 1, term_months: 0 }] };
        }
        // CMTV local change 2026-10-03: a free trial could be added twice (two identical trial lines in the cart)
        const isTrial = (i) => Number(i.price) === 0 && /trial/i.test(i.product_name || '') || !!i.term_label;
        if (isTrial(item)) {
          return { items: [...state.items.filter((i) => !(i.product_id === item.product_id && isTrial(i))), item] };
        }
        return { items: [...state.items, item] };
      }),
      updateQuantity: (product_id, quantity) => set((state) => ({
        items: state.items.map((i) => i.item_type === 'physical' && i.product_id === product_id ? { ...i, quantity: Math.max(1, quantity) } : i),
      })),
      hasPhysicalItems: () => get().items.some((i) => i.item_type === 'physical'),
      // Add item specifically for renewal/extension
      addRenewalItem: (item, serviceId, actionType = 'extend') => set((state) => ({ 
        items: [...state.items, { 
          ...item, 
          renewal_service_id: serviceId,
          action_type: actionType  // 'extend' or 'create_new'
        }] 
      })),
      // Update action type for an item
      updateItemAction: (product_id, term_months, actionType, serviceId = null) =>
        set((state) => ({
          items: state.items.map((item) =>
            item.product_id === product_id && item.term_months === term_months
              ? { ...item, action_type: actionType, renewal_service_id: serviceId }
              : item
          ),
        })),
      removeItem: (product_id, term_months) =>
        set((state) => {
          const idx = state.items.findIndex(
            (item) => item.product_id === product_id && item.term_months === term_months
          );
          if (idx === -1) return state;
          const newItems = [...state.items];
          newItems.splice(idx, 1);
          return { items: newItems };
        }),
      clearCart: () => set({ items: [] }),
      getTotal: () => get().items.reduce((sum, item) => sum + item.price * (item.quantity || 1), 0),
    }),
    {
      name: 'cart-storage',
      partialize: (state) => ({ items: state.items })  // Explicitly persist items array with all fields
    }
  )
);
