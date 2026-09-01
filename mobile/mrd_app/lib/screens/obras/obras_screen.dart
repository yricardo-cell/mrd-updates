import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/local_database.dart';
import '../../models/models.dart';
import '../../config/theme.dart';

class ObrasScreen extends StatefulWidget {
  const ObrasScreen({super.key});
  @override
  State<ObrasScreen> createState() => _ObrasScreenState();
}

class _ObrasScreenState extends State<ObrasScreen> {
  List<Obra> _items = [];
  bool _loading = true;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await ApiService.instance.get('/api/v1/obras');
      final list = (r.data['items'] as List?)?.map((j) => Obra.fromJson(j)).toList() ?? [];
      await LocalDatabase.instance.cacheObras(list);
      if (mounted) setState(() { _items = list; _loading = false; });
    } catch (_) {
      final cached = await LocalDatabase.instance.getCachedObras();
      if (mounted) setState(() { _items = cached; _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Obras'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
      ]),
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: MrdTheme.secondary))
        : RefreshIndicator(
            onRefresh: _load,
            child: ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: _items.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (_, i) {
                final o = _items[i];
                return Card(
                  child: ListTile(
                    leading: const CircleAvatar(
                      backgroundColor: Color(0x3319875),
                      child: Icon(Icons.business, color: MrdTheme.success, size: 20),
                    ),
                    title: Text(o.nombre, style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: Text('${o.codigo} · ${o.estado}'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.pushNamed(context, '/obras/detalle', arguments: o),
                  ),
                );
              },
            ),
          ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => Navigator.pushNamed(context, '/obras/nueva'),
        backgroundColor: MrdTheme.secondary,
        child: const Icon(Icons.add, color: Colors.white),
      ),
    );
  }
}
