import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/local_database.dart';
import '../../models/models.dart';
import '../../config/theme.dart';
import '../../widgets/offline_banner.dart';

class HerramientasScreen extends StatefulWidget {
  const HerramientasScreen({super.key});
  @override
  State<HerramientasScreen> createState() => _HerramientasScreenState();
}

class _HerramientasScreenState extends State<HerramientasScreen> {
  List<Herramienta> _items = [];
  bool _loading = true;
  final _searchCtrl = TextEditingController();
  String _filtroEstado = 'todos';

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await ApiService.instance.get('/api/v1/herramientas',
        params: {'per_page': '200'});
      final list = (r.data['items'] as List?)?.map((j) => Herramienta.fromJson(j)).toList() ?? [];
      await LocalDatabase.instance.cacheHerramientas(list);
      if (mounted) setState(() { _items = list; _loading = false; });
    } catch (_) {
      final cached = await LocalDatabase.instance.getCachedHerramientas();
      if (mounted) setState(() { _items = cached; _loading = false; });
    }
  }

  List<Herramienta> get _filtered {
    final q = _searchCtrl.text.toLowerCase();
    return _items.where((h) {
      final matchQ = q.isEmpty || h.nombre.toLowerCase().contains(q) || h.codigo.toLowerCase().contains(q);
      final matchE = _filtroEstado == 'todos' || h.estado == _filtroEstado;
      return matchQ && matchE;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Herramientas'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
        ],
      ),
      body: Column(
        children: [
          const OfflineBanner(),
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _searchCtrl,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                hintText: 'Buscar herramienta o código...',
                prefixIcon: Icon(Icons.search),
                isDense: true,
              ),
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              children: ['todos','disponible','en_uso','mantenimiento','baja'].map((e) =>
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(e == 'todos' ? 'Todos' : e.replaceAll('_', ' ')),
                    selected: _filtroEstado == e,
                    onSelected: (_) => setState(() => _filtroEstado = e),
                    selectedColor: MrdTheme.secondary.withOpacity(0.3),
                  ),
                )
              ).toList(),
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: _loading
              ? const Center(child: CircularProgressIndicator(color: MrdTheme.secondary))
              : ListView.separated(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  itemCount: _filtered.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (_, i) => _HerramientaTile(item: _filtered[i]),
                ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => Navigator.pushNamed(context, '/herramientas/nueva'),
        backgroundColor: MrdTheme.secondary,
        child: const Icon(Icons.add, color: Colors.white),
      ),
    );
  }
}

class _HerramientaTile extends StatelessWidget {
  final Herramienta item;
  const _HerramientaTile({required this.item});
  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: item.estadoColor.withOpacity(0.15),
          child: Icon(Icons.build, color: item.estadoColor, size: 20),
        ),
        title: Text(item.nombre, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text('${item.codigo} · ${item.categoria ?? "Sin categoría"}',
          style: const TextStyle(fontSize: 12)),
        trailing: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(
            color: item.estadoColor.withOpacity(0.15),
            borderRadius: BorderRadius.circular(6),
            border: Border.all(color: item.estadoColor.withOpacity(0.4)),
          ),
          child: Text(item.estado.replaceAll('_', ' '),
            style: TextStyle(color: item.estadoColor, fontSize: 11, fontWeight: FontWeight.w600)),
        ),
        onTap: () => Navigator.pushNamed(context, '/herramientas/detalle', arguments: item),
      ),
    );
  }
}
