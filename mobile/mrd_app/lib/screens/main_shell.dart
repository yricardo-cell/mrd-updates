import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../services/local_database.dart';
import '../config/theme.dart';
import 'dashboard_screen.dart';
import 'scanner_screen.dart';
import 'herramientas/herramientas_screen.dart';
import 'obras/obras_screen.dart';
import 'mas_screen.dart';

class MainShell extends StatefulWidget {
  const MainShell({super.key});
  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _tab = 0;
  int _pendingSync = 0;

  final _pages = const [
    DashboardScreen(),
    HerramientasScreen(),
    ScannerScreen(),
    ObrasScreen(),
    MasScreen(),
  ];

  @override
  void initState() {
    super.initState();
    _loadPending();
  }

  Future<void> _loadPending() async {
    final n = await LocalDatabase.instance.pendingCount();
    if (mounted) setState(() => _pendingSync = n);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _tab, children: _pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        backgroundColor: MrdTheme.surfaceDark,
        indicatorColor: MrdTheme.secondary.withOpacity(0.2),
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard, color: MrdTheme.secondary),
            label: 'Inicio',
          ),
          const NavigationDestination(
            icon: Icon(Icons.build_outlined),
            selectedIcon: Icon(Icons.build, color: MrdTheme.secondary),
            label: 'Herramientas',
          ),
          NavigationDestination(
            icon: Container(
              padding: const EdgeInsets.all(8),
              decoration: const BoxDecoration(
                color: MrdTheme.secondary,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.qr_code_scanner, color: Colors.white, size: 28),
            ),
            label: 'Escáner',
          ),
          const NavigationDestination(
            icon: Icon(Icons.business_outlined),
            selectedIcon: Icon(Icons.business, color: MrdTheme.secondary),
            label: 'Obras',
          ),
          NavigationDestination(
            icon: _pendingSync > 0
              ? Badge(label: Text('$_pendingSync'), child: const Icon(Icons.more_horiz))
              : const Icon(Icons.more_horiz),
            label: 'Más',
          ),
        ],
      ),
    );
  }
}
