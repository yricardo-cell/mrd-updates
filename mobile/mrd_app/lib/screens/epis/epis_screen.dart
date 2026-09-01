import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../config/theme.dart';

class EpisScreen extends StatefulWidget {
  const EpisScreen({super.key});
  @override
  State<EpisScreen> createState() => _EpisScreenState();
}

class _EpisScreenState extends State<EpisScreen> {
  List<Map<String, dynamic>> _items = [];
  bool _loading = true;
  final _searchCtrl = TextEditingController();

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await ApiService.instance.get('/api/v1/epis');
      final raw = r.data;
      final list = (raw['items'] ?? raw) as List?;
      if (mounted) setState(() {
        _items = list?.cast<Map<String,dynamic>>() ?? [];
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<Map<String, dynamic>> get _filtered {
    final q = _searchCtrl.text.toLowerCase();
    if (q.isEmpty) return _items;
    return _items.where((i) => i.values.any((v) => v.toString().toLowerCase().contains(q))).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Epis'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
      ]),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(12),
            child: TextField(
              controller: _searchCtrl,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                hintText: 'Buscar...', prefixIcon: Icon(Icons.search), isDense: true),
            ),
          ),
          Expanded(
            child: _loading
              ? const Center(child: CircularProgressIndicator(color: MrdTheme.secondary))
              : _filtered.isEmpty
                ? const Center(child: Text('Sin registros'))
                : ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    itemCount: _filtered.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (_, i) {
                      final item = _filtered[i];
                      final title = item['nombre'] ?? item['matricula'] ?? item['codigo'] ?? '—';
                      final subtitle = item['estado'] ?? item['puesto'] ?? item['unidad'] ?? '';
                      return Card(
                        child: ListTile(
                          leading: const CircleAvatar(
                            backgroundColor: Color(0x221E3A5F),
                            child: Icon(Icons.circle, color: MrdTheme.accent, size: 10)),
                          title: Text(title.toString(),
                            style: const TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: subtitle.toString().isNotEmpty ? Text(subtitle.toString()) : null,
                          trailing: const Icon(Icons.chevron_right),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
