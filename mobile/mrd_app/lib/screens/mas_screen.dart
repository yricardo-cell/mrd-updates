import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../services/local_database.dart';
import '../config/theme.dart';
import 'trabajadores/trabajadores_screen.dart';
import 'vehiculos/vehiculos_screen.dart';
import 'materiales/materiales_screen.dart';
import 'epis/epis_screen.dart';
import 'incidencias/incidencias_screen.dart';

class MasScreen extends StatefulWidget {
  const MasScreen({super.key});
  @override
  State<MasScreen> createState() => _MasScreenState();
}

class _MasScreenState extends State<MasScreen> {
  int _pendingSync = 0;
  @override
  void initState() { super.initState(); _loadPending(); }

  Future<void> _loadPending() async {
    final n = await LocalDatabase.instance.pendingCount();
    if (mounted) setState(() => _pendingSync = n);
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthService>().user;
    return Scaffold(
      appBar: AppBar(title: const Text('Más opciones')),
      body: ListView(
        children: [
          // Perfil
          ListTile(
            leading: CircleAvatar(
              backgroundColor: MrdTheme.primary,
              child: Text(user?.nombre.substring(0,1).toUpperCase() ?? 'U',
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            ),
            title: Text(user?.fullName ?? 'Usuario'),
            subtitle: Text(user?.role ?? ''),
          ),
          const Divider(),

          // Módulos
          _Section(title: 'MÓDULOS'),
          _Tile(icon: Icons.people, label: 'Trabajadores', color: MrdTheme.accent,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const TrabajadoresScreen()))),
          _Tile(icon: Icons.directions_car, label: 'Vehículos', color: MrdTheme.primary,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const VehiculosScreen()))),
          _Tile(icon: Icons.inventory_2, label: 'Materiales', color: Colors.teal,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const MaterialesScreen()))),
          _Tile(icon: Icons.shield, label: 'EPIs y Ropa', color: Colors.purple,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const EpisScreen()))),
          _Tile(icon: Icons.warning_amber, label: 'Incidencias', color: MrdTheme.danger,
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const IncidenciasScreen()))),

          const Divider(),
          _Section(title: 'SISTEMA'),

          if (_pendingSync > 0)
            ListTile(
              leading: const Icon(Icons.sync, color: MrdTheme.warning),
              title: Text('$_pendingSync pendientes de sincronizar'),
              trailing: ElevatedButton(
                onPressed: () async {
                  await LocalDatabase.instance.processQueue();
                  _loadPending();
                },
                child: const Text('Sincronizar'),
              ),
            ),

          _Tile(icon: Icons.settings, label: 'Configuración', color: Colors.grey,
            onTap: () => Navigator.pushNamed(context, '/settings')),

          _Tile(icon: Icons.logout, label: 'Cerrar sesión', color: MrdTheme.danger,
            onTap: () async {
              final confirm = await showDialog<bool>(context: context, builder: (_) =>
                AlertDialog(
                  backgroundColor: MrdTheme.cardDark,
                  title: const Text('Cerrar sesión'),
                  content: const Text('¿Seguro que quieres cerrar sesión?'),
                  actions: [
                    TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
                    TextButton(onPressed: () => Navigator.pop(context, true),
                      child: const Text('Cerrar sesión', style: TextStyle(color: MrdTheme.danger))),
                  ],
                ));
              if (confirm == true && context.mounted) {
                await context.read<AuthService>().logout();
                Navigator.pushNamedAndRemoveUntil(context, '/login', (_) => false);
              }
            }),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  const _Section({required this.title});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
    child: Text(title, style: const TextStyle(fontSize: 11, color: Colors.white38, letterSpacing: 1.2)),
  );
}

class _Tile extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;
  const _Tile({required this.icon, required this.label, required this.color, required this.onTap});
  @override
  Widget build(BuildContext context) => ListTile(
    leading: CircleAvatar(radius: 18, backgroundColor: color.withOpacity(0.15),
      child: Icon(icon, color: color, size: 20)),
    title: Text(label),
    trailing: const Icon(Icons.chevron_right, color: Colors.white30),
    onTap: onTap,
  );
}
