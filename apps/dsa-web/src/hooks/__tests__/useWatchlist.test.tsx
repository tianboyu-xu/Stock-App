import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWatchlist } from '../useWatchlist';

const {
  mockGetWatchlist,
  mockAddToWatchlist,
  mockRemoveFromWatchlist,
  mockReorderWatchlist,
} = vi.hoisted(() => ({
  mockGetWatchlist: vi.fn(),
  mockAddToWatchlist: vi.fn(),
  mockRemoveFromWatchlist: vi.fn(),
  mockReorderWatchlist: vi.fn(),
}));

vi.mock('../../api/systemConfig', () => ({
  systemConfigApi: {
    getWatchlist: mockGetWatchlist,
    addToWatchlist: mockAddToWatchlist,
    removeFromWatchlist: mockRemoveFromWatchlist,
    reorderWatchlist: mockReorderWatchlist,
  },
}));

describe('useWatchlist', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetWatchlist.mockResolvedValue([]);
    mockAddToWatchlist.mockResolvedValue([]);
    mockRemoveFromWatchlist.mockResolvedValue([]);
    mockReorderWatchlist.mockResolvedValue([]);
  });

  it('matches raw HK watchlist entries against prefixed and suffixed variants', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isInWatchlist('00700')).toBe(true);
    expect(result.current.isInWatchlist('HK00700')).toBe(true);
    expect(result.current.isInWatchlist('00700.HK')).toBe(true);
    expect(result.current.isInWatchlist('HK01810')).toBe(false);
  });

  it('removes the matched raw watchlist entry instead of adding a duplicate variant', async () => {
    mockGetWatchlist.mockResolvedValue(['00700']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.toggleWatchlist('HK00700');
    });

    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('00700');
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.watchlistCodes).toEqual([]);
    });
  });

  it('compares submitted and stored US tickers case-insensitively', async () => {
    mockGetWatchlist.mockResolvedValue(['aapl']);
    mockRemoveFromWatchlist.mockResolvedValue([]);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isInWatchlist('AAPL')).toBe(true);

    await act(async () => {
      await result.current.toggleWatchlist('AAPL');
    });

    expect(mockRemoveFromWatchlist).toHaveBeenCalledWith('aapl');
    expect(mockAddToWatchlist).not.toHaveBeenCalled();
  });

  it('reorders the watchlist and updates the stored codes', async () => {
    mockGetWatchlist.mockResolvedValue(['600519', '000001', 'AAPL']);
    mockReorderWatchlist.mockResolvedValue(['AAPL', '600519', '000001']);

    const { result } = renderHook(() => useWatchlist());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.reorderWatchlist(['AAPL', '600519', '000001']);
    });

    expect(mockReorderWatchlist).toHaveBeenCalledWith(['AAPL', '600519', '000001']);
    await waitFor(() => {
      expect(result.current.watchlistCodes).toEqual(['AAPL', '600519', '000001']);
    });
  });
});
