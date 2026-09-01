import 'package:flutter/material.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import '../config/theme.dart';

class OfflineBanner extends StatefulWidget {
  const OfflineBanner({super.key});
  @override
  State<OfflineBanner> createState() => _OfflineBannerState();
}

class _OfflineBannerState extends State<OfflineBanner> {
  bool _offline = false;

  @override
  void initState() {
    super.initState();
    Connectivity().onConnectivityChanged.listen((results) {
      final offline = results.every((r) => r == ConnectivityResult.none);
      if (mounted && offline != _offline) setState(() => _offline = offline);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!_offline) return const SizedBox.shrink();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: MrdTheme.warning.withOpacity(0.15),
      child: Row(
        children: [
          const Icon(Icons.wifi_off, color: MrdTheme.warning, size: 16),
          const SizedBox(width: 8),
          const Expanded(
            child: Text('Sin conexión — Modo offline activo',
              style: TextStyle(color: MrdTheme.warning, fontSize: 12)),
          ),
        ],
      ),
    );
  }
}
