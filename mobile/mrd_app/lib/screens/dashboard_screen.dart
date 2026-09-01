import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../services/api_service.dart';
import '../config/theme.dart';
import '../widgets/stat_card.dart';
import '../widgets/offline_banner.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});
  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic> _stats = {};
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadStats();
  }

  Future<void> _loadStats() async {
    setState(() => _loading = true);
    try {
      final r = await ApiService.instance.get('/api/stats');
      if (mounted) setState(() { _stats = r.data as Map<String, dynamic>; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthService>().user;
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('MRD TOOL CONTROL'),
            Text('Hola, ${user?.nombre ?? 'Usuario'}',
              style: const TextStyle(fontSize: 12, color: Colors.white70)),
          ],
        ),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _loadStats),
          IconButton(
            icon: const Icon(Icons.notifications_outlined),
            onPressed: () => Navigator.pushNamed(context, '/notificaciones'),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _loadStats,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const OfflineBanner(),
            if (_loading)
              const Center(child: Padding(
                padding: EdgeInsets.all(32),
                child: CircularProgressIndicator(color: MrdTheme.secondary),
              ))
            else ...[
              // Stats grid
              GridView.count(
                crossAxisCount: 2,
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                childAspectRatio: 1.4,
                children: [
                  StatCard(
                    label: 'Herramientas',
                    value: '${_stats['total_herramientas'] ?? 0}',
                    icon: Icons.build,
                    color: MrdTheme.accent,
                    onTap: () => Navigator.pushNamed(context, '/herramientas'),
                  ),
                  StatCard(
                    label: 'En uso',
                    value: '${_stats['herramientas_en_uso'] ?? 0}',
                    icon: Icons.engineering,
                    color: MrdTheme.secondary,
                    onTap: () => Navigator.pushNamed(context, '/herramientas'),
                  ),
                  StatCard(
                    label: 'Obras activas',
                    value: '${_stats['obras_activas'] ?? 0}',
                    icon: Icons.business,
                    color: MrdTheme.success,
                    onTap: () => Navigator.pushNamed(context, '/obras'),
                  ),
                  StatCard(
                    label: 'Incidencias',
                    value: '${_stats['incidencias_abiertas'] ?? 0}',
                    icon: Icons.warning_amber,
                    color: MrdTheme.danger,
                    onTap: () => Navigator.pushNamed(context, '/incidencias'),
                  ),
                ],
              ),
              const SizedBox(height: 20),

              // Accesos rápidos
              Text('Acciones rápidas',
                style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 12),
              Wrap(
                spacing: 10, runSpacing: 10,
                children: [
                  _QuickAction(icon: Icons.qr_code_scanner, label: 'Escanear',
                    onTap: () => Navigator.pushNamed(context, '/scanner')),
                  _QuickAction(icon: Icons.add_circle_outline, label: 'Incidencia',
                    onTap: () => Navigator.pushNamed(context, '/incidencias/nueva')),
                  _QuickAction(icon: Icons.people_outline, label: 'Trabajadores',
                    onTap: () => Navigator.pushNamed(context, '/trabajadores')),
                  _QuickAction(icon: Icons.inventory_2_outlined, label: 'Materiales',
                    onTap: () => Navigator.pushNamed(context, '/materiales')),
                  _QuickAction(icon: Icons.directions_car_outlined, label: 'Vehículos',
                    onTap: () => Navigator.pushNamed(context, '/vehiculos')),
                  _QuickAction(icon: Icons.shield_outlined, label: 'EPIs',
                    onTap: () => Navigator.pushNamed(context, '/epis')),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _QuickAction extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  const _QuickAction({required this.icon, required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        width: 90, height: 80,
        decoration: BoxDecoration(
          color: MrdTheme.cardDark,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: MrdTheme.secondary, size: 28),
            const SizedBox(height: 6),
            Text(label, style: const TextStyle(fontSize: 11, color: Colors.white70)),
          ],
        ),
      ),
    );
  }
}
